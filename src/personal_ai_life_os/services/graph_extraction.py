"""Evidence graph extraction from explicitly selected source items."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import (
    EntityAlias,
    ExtractionRun,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    GraphReviewItem,
    ModelRun,
    OntologyType,
    SourceConnection,
    SourceItem,
    utcnow,
)
from personal_ai_life_os.services.ontology import approved_names

logger = logging.getLogger(__name__)
PROMPT_VERSION = "graph-extraction-v1"
CORE_ENTITY_TYPES = {
    "project",
    "goal",
    "task",
    "topic",
    "skill",
    "growth_record",
    "person",
    "event",
    "decision",
    "commitment",
}
CORE_RELATION_TYPES = {
    "has_goal",
    "has_task",
    "supports_goal",
    "part_of",
    "related_to",
    "evidenced_by",
    "committed_to",
    "decided_in",
    "involves",
    "develops_skill",
}
SYSTEM_PROMPT = (
    "Extract an evidence graph from the supplied personal source items. Return JSON only with "
    '{"entities":[...],"relations":[...]}. Each entity needs type, name, summary, confidence '
    "(0..1), and evidence: a list of {item_id, quote}. Each relation needs from_key, to_key, "
    "type, confidence, and evidence. Use only supplied item IDs and exact short quotes from the "
    "text. Prefer project, goal, task, topic, skill, growth_record, person, event, decision, and "
    "commitment. Do not invent facts or dates."
)


class GraphExtractionError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class GraphModelProvider:
    name: str
    base_url: str
    api_key: str
    model: str
    input_cost_per_million_usd: Decimal
    output_cost_per_million_usd: Decimal


def _parse_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal(0)


def resolve_model_provider(config: Settings, requested: str | None) -> GraphModelProvider:
    if requested:
        if not config.graph_model_providers:
            raise GraphExtractionError(
                "model_provider_unavailable",
                "The requested model provider is not configured.",
                409,
            )
        try:
            providers = json.loads(config.graph_model_providers)
        except json.JSONDecodeError as error:
            raise GraphExtractionError(
                "model_provider_unconfigured",
                "GRAPH_MODEL_PROVIDERS must be valid JSON.",
                409,
            ) from error
        if not isinstance(providers, dict) or not isinstance(providers.get(requested), dict):
            raise GraphExtractionError(
                "model_provider_unavailable",
                "The requested model provider is not configured.",
                409,
            )
        entry = providers[requested]
        base_url = str(entry.get("base_url") or "").rstrip("/")
        api_key = str(entry.get("api_key") or "")
        model = str(entry.get("model") or "")
        if not base_url or not api_key or not model:
            raise GraphExtractionError(
                "model_provider_unconfigured",
                "The requested model provider is missing base_url, api_key, or model.",
                409,
            )
        return GraphModelProvider(
            name=requested,
            base_url=base_url,
            api_key=api_key,
            model=model,
            input_cost_per_million_usd=_parse_decimal(
                entry.get("input_cost_per_million_usd")
            ),
            output_cost_per_million_usd=_parse_decimal(
                entry.get("output_cost_per_million_usd")
            ),
        )
    if config.model_provider != "openai" or not config.openai_api_key:
        raise GraphExtractionError(
            "model_provider_unavailable",
            "Configure an OpenAI-compatible provider before extracting.",
            409,
        )
    return GraphModelProvider(
        name=config.model_provider,
        base_url=config.openai_base_url.rstrip("/"),
        api_key=config.openai_api_key,
        model=config.openai_model,
        input_cost_per_million_usd=config.model_input_cost_per_million_usd,
        output_cost_per_million_usd=config.model_output_cost_per_million_usd,
    )


def _provider_cost(
    provider: GraphModelProvider, input_tokens: int, output_tokens: int
) -> Decimal | None:
    if (
        provider.input_cost_per_million_usd <= 0
        or provider.output_cost_per_million_usd <= 0
    ):
        return None
    return (
        Decimal(input_tokens) * provider.input_cost_per_million_usd
        + Decimal(output_tokens) * provider.output_cost_per_million_usd
    ) / Decimal(1_000_000)


def _estimate_tokens(items: list[SourceItem]) -> int:
    payload = json.dumps(
        [
            {"item_id": item.id, "title": item.title[:240], "text": item.content_text[:4000]}
            for item in items
        ],
        ensure_ascii=False,
    )
    return len(SYSTEM_PROMPT) + len(payload)


def _call_graph_model(
    items: list[SourceItem],
    config: Settings,
    provider: GraphModelProvider,
    custom_types: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], int, int, int]:
    system_prompt = SYSTEM_PROMPT
    if custom_types:
        entity_types = ", ".join(sorted(custom_types.get("entity") or []))
        relation_types = ", ".join(sorted(custom_types.get("relation") or []))
        if entity_types:
            system_prompt += "\nApproved custom entity types: " + entity_types + "."
        if relation_types:
            system_prompt += "\nApproved custom relation types: " + relation_types + "."
    evidence = [
        {
            "item_id": item.id,
            "title": item.title[:240],
            "date": item.occurred_at.isoformat() if item.occurred_at else None,
            "text": item.content_text[:4000],
        }
        for item in items
    ]
    started = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
        response = client.post(
            provider.base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + provider.api_key},
            json={
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
                ],
                "temperature": 0.0,
                "max_tokens": config.model_max_output_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        result = response.json()
    latency = int((time.monotonic() - started) * 1000)
    content = result.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
    document = json.loads(content)
    if not isinstance(document, dict):
        raise TypeError("Graph extraction output must be a JSON object.")
    usage = result.get("usage", {})
    return (
        document,
        latency,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
    )


def monthly_spend(session: Session, owner_id: str, now: datetime | None = None) -> Decimal:
    current = now or utcnow()
    month_start = datetime(current.year, current.month, 1, tzinfo=UTC)
    value = session.scalar(
        select(func.coalesce(func.sum(ModelRun.cost_usd), 0)).where(
            ModelRun.owner_id == owner_id,
            ModelRun.created_at >= month_start,
        )
    )
    return Decimal(str(value or 0))


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _evidence_payload(value: Any, item_map: dict[str, SourceItem]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        quote = entry.get("quote")
        if isinstance(item_id, str) and item_id in item_map and isinstance(quote, str) and quote.strip():
            result.append({"item_id": item_id, "quote": quote.strip()[:2000]})
    return result


def _validate_confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return 0.5


def _entity_type_valid(session: Session, owner_id: str, entity_type: str) -> bool:
    if entity_type in CORE_ENTITY_TYPES:
        return True
    approved = session.scalar(
        select(OntologyType.id).where(
            OntologyType.owner_id == owner_id,
            OntologyType.kind == "entity",
            OntologyType.name == entity_type,
            OntologyType.status == "approved",
        )
    )
    if approved is not None:
        return True
    existing = session.scalar(
        select(OntologyType).where(
            OntologyType.owner_id == owner_id,
            OntologyType.kind == "entity",
            OntologyType.name == entity_type,
        )
    )
    if existing is None:
        session.add(
            OntologyType(
                owner_id=owner_id,
                kind="entity",
                name=entity_type[:64],
                description="Proposed by graph extraction.",
                status="proposed",
                source="model",
            )
        )
    return False


def _relation_type_valid(session: Session, owner_id: str, relation_type: str) -> bool:
    if relation_type in CORE_RELATION_TYPES:
        return True
    approved = session.scalar(
        select(OntologyType.id).where(
            OntologyType.owner_id == owner_id,
            OntologyType.kind == "relation",
            OntologyType.name == relation_type,
            OntologyType.status == "approved",
        )
    )
    if approved is not None:
        return True
    existing = session.scalar(
        select(OntologyType).where(
            OntologyType.owner_id == owner_id,
            OntologyType.kind == "relation",
            OntologyType.name == relation_type,
        )
    )
    if existing is None:
        session.add(
            OntologyType(
                owner_id=owner_id,
                kind="relation",
                name=relation_type[:64],
                description="Proposed by graph extraction.",
                status="proposed",
                source="model",
            )
        )
    return False


def _find_or_create_entity(
    session: Session,
    *,
    owner_id: str,
    entity_type: str,
    name: str,
    summary: str | None,
    confidence: float,
    threshold: float,
) -> tuple[GraphEntity, bool]:
    normalized = _normalize(name)
    existing = session.scalar(
        select(GraphEntity).where(
            GraphEntity.owner_id == owner_id,
            GraphEntity.entity_type == entity_type,
            GraphEntity.normalized_name == normalized,
            GraphEntity.status.in_(("active", "pending_review")),
        )
    )
    if existing is not None:
        if not existing.summary and summary:
            existing.summary = summary
        existing.confidence = max(existing.confidence, confidence)
        if existing.name != name:
            alias_exists = session.scalar(
                select(EntityAlias.id).where(
                    EntityAlias.owner_id == owner_id,
                    EntityAlias.entity_id == existing.id,
                    EntityAlias.normalized_alias == normalized,
                )
            )
            if alias_exists is None:
                session.add(
                    EntityAlias(
                        owner_id=owner_id,
                        entity_id=existing.id,
                        alias=name[:500],
                        normalized_alias=normalized,
                    )
                )
        return existing, False
    alias_entity = session.scalar(
        select(GraphEntity)
        .join(EntityAlias, EntityAlias.entity_id == GraphEntity.id)
        .where(
            GraphEntity.owner_id == owner_id,
            GraphEntity.entity_type == entity_type,
            GraphEntity.status == "active",
            EntityAlias.normalized_alias == normalized,
        )
        .order_by(GraphEntity.confidence.desc(), GraphEntity.updated_at.desc())
    )
    if alias_entity is not None:
        if not alias_entity.summary and summary:
            alias_entity.summary = summary
        alias_entity.confidence = max(alias_entity.confidence, confidence)
        if alias_entity.name != name:
            exists = session.scalar(
                select(EntityAlias.id).where(
                    EntityAlias.owner_id == owner_id,
                    EntityAlias.entity_id == alias_entity.id,
                    EntityAlias.normalized_alias == normalized,
                )
            )
            if exists is None:
                session.add(
                    EntityAlias(
                        owner_id=owner_id,
                        entity_id=alias_entity.id,
                        alias=name[:500],
                        normalized_alias=normalized,
                    )
                )
        return alias_entity, False
    entity = GraphEntity(
        owner_id=owner_id,
        entity_type=entity_type,
        name=name[:500],
        normalized_name=normalized,
        summary=summary,
        confidence=confidence,
        status="active" if confidence >= threshold else "pending_review",
        created_by="model",
    )
    session.add(entity)
    session.flush()
    return entity, True


def _find_or_create_relation(
    session: Session,
    *,
    owner_id: str,
    from_entity_id: str,
    to_entity_id: str,
    relation_type: str,
    confidence: float,
    threshold: float,
) -> tuple[GraphRelation, bool]:
    existing = session.scalar(
        select(GraphRelation).where(
            GraphRelation.owner_id == owner_id,
            GraphRelation.from_entity_id == from_entity_id,
            GraphRelation.to_entity_id == to_entity_id,
            GraphRelation.relation_type == relation_type,
            GraphRelation.status.in_(("active", "pending_review")),
        )
    )
    if existing is not None:
        existing.confidence = max(existing.confidence, confidence)
        return existing, False
    relation = GraphRelation(
        owner_id=owner_id,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relation_type=relation_type,
        confidence=confidence,
        status="active" if confidence >= threshold else "pending_review",
        created_by="model",
    )
    session.add(relation)
    session.flush()
    return relation, True


def _add_evidence(
    session: Session,
    *,
    owner_id: str,
    item_map: dict[str, SourceItem],
    evidence: list[dict[str, Any]],
    entity_id: str | None = None,
    relation_id: str | None = None,
    confidence: float,
) -> int:
    created = 0
    for entry in evidence:
        item = item_map[entry["item_id"]]
        existing = session.scalar(
            select(GraphEvidence.id).where(
                GraphEvidence.owner_id == owner_id,
                GraphEvidence.entity_id == entity_id,
                GraphEvidence.relation_id == relation_id,
                GraphEvidence.source_item_id == item.id,
                GraphEvidence.quote == entry["quote"],
            )
        )
        if existing is not None:
            continue
        session.add(
            GraphEvidence(
                owner_id=owner_id,
                entity_id=entity_id,
                relation_id=relation_id,
                source_id=item.source_id,
                source_item_id=item.id,
                quote=entry["quote"],
                locator=item.source_locator,
                confidence=confidence,
                availability="active",
            )
        )
        created += 1
    return created


def _add_review(
    session: Session,
    *,
    owner_id: str,
    run_id: str,
    kind: str,
    payload: dict[str, Any],
    confidence: float,
    reason: str,
) -> None:
    session.add(
        GraphReviewItem(
            owner_id=owner_id,
            extraction_run_id=run_id,
            kind=kind,
            payload=payload,
            confidence=confidence,
            status="pending",
            reason=reason,
        )
    )


def _persist_graph(
    session: Session,
    *,
    owner_id: str,
    run_id: str,
    document: dict[str, Any],
    item_map: dict[str, SourceItem],
    threshold: float,
) -> tuple[int, int, int]:
    entities = document.get("entities", [])
    relations = document.get("relations", [])
    if not isinstance(entities, list) or not isinstance(relations, list):
        raise TypeError("Graph extraction output must contain entity and relation arrays.")

    key_map: dict[str, GraphEntity] = {}
    entity_count = 0
    review_count = 0
    for raw in entities[:200]:
        if not isinstance(raw, dict):
            continue
        entity_type = str(raw.get("type") or "").strip()[:64]
        name = str(raw.get("name") or "").strip()
        if not entity_type or not name:
            continue
        type_valid = _entity_type_valid(session, owner_id, entity_type)
        confidence = _validate_confidence(raw.get("confidence"))
        if not type_valid:
            confidence = min(confidence, 0.4)
        evidence = _evidence_payload(raw.get("evidence"), item_map)
        if not evidence:
            confidence = min(confidence, 0.4)
        entity, created = _find_or_create_entity(
            session,
            owner_id=owner_id,
            entity_type=entity_type,
            name=name,
            summary=raw.get("summary") if isinstance(raw.get("summary"), str) else None,
            confidence=confidence,
            threshold=threshold,
        )
        key = str(raw.get("key") or name)
        key_map[key] = entity
        if created:
            entity_count += 1
        _add_evidence(
            session,
            owner_id=owner_id,
            item_map=item_map,
            evidence=evidence,
            entity_id=entity.id,
            confidence=confidence,
        )
        if confidence < threshold:
            _add_review(
                session,
                owner_id=owner_id,
                run_id=run_id,
                kind="entity",
                payload={"entity_id": entity.id, "name": name, "type": entity_type},
                confidence=confidence,
                reason="low_confidence" if evidence else "missing_evidence",
            )
            review_count += 1

    relation_count = 0
    for raw in relations[:300]:
        if not isinstance(raw, dict):
            continue
        from_key = str(raw.get("from_key") or "")
        to_key = str(raw.get("to_key") or "")
        relation_type = str(raw.get("type") or "").strip()[:64]
        source_entity = key_map.get(from_key)
        target_entity = key_map.get(to_key)
        if source_entity is None or target_entity is None or source_entity.id == target_entity.id or not relation_type:
            continue
        type_valid = _relation_type_valid(session, owner_id, relation_type)
        confidence = _validate_confidence(raw.get("confidence"))
        if not type_valid:
            confidence = min(confidence, 0.4)
        evidence = _evidence_payload(raw.get("evidence"), item_map)
        if not evidence:
            confidence = min(confidence, 0.4)
        relation, created = _find_or_create_relation(
            session,
            owner_id=owner_id,
            from_entity_id=source_entity.id,
            to_entity_id=target_entity.id,
            relation_type=relation_type,
            confidence=confidence,
            threshold=threshold,
        )
        if created:
            relation_count += 1
        _add_evidence(
            session,
            owner_id=owner_id,
            item_map=item_map,
            evidence=evidence,
            relation_id=relation.id,
            confidence=confidence,
        )
        if confidence < threshold:
            _add_review(
                session,
                owner_id=owner_id,
                run_id=run_id,
                kind="relation",
                payload={
                    "relation_id": relation.id,
                    "from_entity_id": source_entity.id,
                    "to_entity_id": target_entity.id,
                    "relation_type": relation_type,
                },
                confidence=confidence,
                reason="low_confidence" if evidence else "missing_evidence",
            )
            review_count += 1
    return entity_count, relation_count, review_count


def extract_selected_items(
    session: Session,
    *,
    owner_id: str,
    item_ids: list[str],
    config: Settings,
    provider_name: str | None = None,
) -> ExtractionRun:
    unique_ids = sorted(set(item_ids))
    if not unique_ids:
        raise GraphExtractionError("item_selection_required", "Choose at least one source item.", 422)
    if len(unique_ids) > config.graph_extraction_max_items:
        raise GraphExtractionError(
            "extraction_batch_too_large",
            f"Select at most {config.graph_extraction_max_items} items per extraction.",
            413,
        )
    rows = list(
        session.execute(
            select(SourceItem, SourceConnection)
            .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
            .where(
                SourceItem.owner_id == owner_id,
                SourceItem.id.in_(unique_ids),
                SourceItem.deleted_at.is_(None),
                SourceItem.is_current.is_(True),
            )
        ).all()
    )
    if len(rows) != len(unique_ids):
        raise GraphExtractionError("source_item_not_found", "One or more selected items were not found.", 404)
    for _, source in rows:
        if source.status != "active":
            raise GraphExtractionError(
                "source_not_active",
                "Resume the source before extracting graph evidence.",
                409,
            )
        if (
            source.cloud_consent_at is None
            or source.cloud_consent_version != config.graph_cloud_consent_version
        ):
            raise GraphExtractionError(
                "source_cloud_consent_required",
                "Enable current cloud extraction consent for every selected source.",
                409,
            )

    provider = resolve_model_provider(config, provider_name)
    requested_hash = hashlib.sha256(
        json.dumps(
            {
                "item_ids": unique_ids,
                "provider": provider.name,
                "model": provider.model,
                "prompt_version": PROMPT_VERSION,
            },
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    existing = session.scalar(
        select(ExtractionRun)
        .where(
            ExtractionRun.owner_id == owner_id,
            ExtractionRun.requested_hash == requested_hash,
            ExtractionRun.status == "completed",
        )
        .order_by(ExtractionRun.created_at.desc())
    )
    if existing is not None:
        return existing

    items = [item for item, _ in rows]
    estimated_input_tokens = _estimate_tokens(items)
    reserved_cost = _provider_cost(
        provider, estimated_input_tokens, config.model_max_output_tokens
    )
    if reserved_cost is None:
        raise GraphExtractionError(
            "model_cost_unconfigured",
            "Configure current per-token prices before extracting.",
            409,
        )
    if reserved_cost > config.model_max_cost_per_call_usd:
        raise GraphExtractionError(
            "model_cost_per_call_exceeded",
            "This extraction exceeds the configured per-call budget.",
            409,
        )
    spent = monthly_spend(session, owner_id)
    if ((config.model_monthly_budget_usd > 0 or config.app_env == "desktop")
            and spent + reserved_cost > config.model_monthly_budget_usd):
        raise GraphExtractionError(
            "model_budget_exceeded",
            "This extraction would exceed the monthly model budget.",
            409,
        )

    run = ExtractionRun(
        owner_id=owner_id,
        status="running",
        provider=provider.name,
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        requested_hash=requested_hash,
        requested_item_ids=unique_ids,
        item_count=len(items),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        custom_types = {
            "entity": sorted(
                approved_names(session, owner_id=owner_id, kind="entity") - CORE_ENTITY_TYPES
            ),
            "relation": sorted(
                approved_names(session, owner_id=owner_id, kind="relation")
                - CORE_RELATION_TYPES
            ),
        }
        if custom_types["entity"] or custom_types["relation"]:
            document, latency, input_tokens, output_tokens = _call_graph_model(
                items, config, provider, custom_types
            )
        else:
            document, latency, input_tokens, output_tokens = _call_graph_model(
                items, config, provider
            )
        actual_cost = _provider_cost(provider, input_tokens, output_tokens) or reserved_cost
        entity_count, relation_count, review_count = _persist_graph(
            session,
            owner_id=owner_id,
            run_id=run.id,
            document=document,
            item_map={item.id: item for item in items},
            threshold=config.graph_extraction_confidence_threshold,
        )
        run.status = "completed"
        run.entity_count = entity_count
        run.relation_count = relation_count
        run.review_count = review_count
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.cost_usd = actual_cost
        run.latency_ms = latency
        run.completed_at = utcnow()
        session.add(
            ModelRun(
                owner_id=owner_id,
                provider=provider.name,
                model=provider.model,
                purpose="graph_extraction",
                status="succeeded",
                prompt_version=PROMPT_VERSION,
                latency_ms=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=actual_cost,
            )
        )
        session.commit()
        session.refresh(run)
        return run
    except Exception as error:
        session.rollback()
        run = session.get(ExtractionRun, run.id)
        if run is not None:
            run.status = "failed"
            run.error_code = type(error).__name__
            run.input_tokens = estimated_input_tokens
            run.output_tokens = config.model_max_output_tokens
            run.cost_usd = reserved_cost
            run.latency_ms = 0
            run.completed_at = utcnow()
            session.add(
                ModelRun(
                    owner_id=owner_id,
                    provider=provider.name,
                    model=provider.model,
                    purpose="graph_extraction",
                    status="failed",
                    prompt_version=PROMPT_VERSION,
                    latency_ms=0,
                    input_tokens=estimated_input_tokens,
                    output_tokens=config.model_max_output_tokens,
                    cost_usd=reserved_cost,
                )
            )
            session.commit()
        logger.warning("Graph extraction failed (%s).", type(error).__name__)
        raise GraphExtractionError(
            "graph_extraction_failed",
            "Graph extraction failed. Review the run and retry.",
            502,
        ) from error
