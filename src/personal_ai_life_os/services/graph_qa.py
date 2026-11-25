"""Evidence-grounded personal question answering over the local graph and timeline."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from personal_ai_life_os.models import (
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    Review,
    SourceConnection,
    SourceItem,
    utcnow,
)

QA_VERSION = "graph-qa-v1"
MAX_EVIDENCE_ROWS = 500
MAX_CITATIONS = 20
MAX_FACTS = 20
MAX_TIMELINE_MATCHES = 10
MAX_REVIEW_MATCHES = 5

CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
WORD_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{1,}")
STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "me",
    "my",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "一个",
    "什么",
    "以及",
    "你",
    "关于",
    "多少",
    "如何",
    "我们",
    "我",
    "是否",
    "有",
    "的",
    "这个",
    "那个",
    "哪些",
    "怎么",
    "是",
    "最近",
}

INTENT_WORDS: dict[str, tuple[str, ...]] = {
    "decision": (
        "决定",
        "约定",
        "承诺",
        "答应",
        "为什么",
        "decide",
        "decided",
        "decision",
        "promise",
        "commitment",
        "committed",
        "agree",
        "agreed",
    ),
    "project": (
        "项目",
        "目标",
        "进度",
        "下一步",
        "计划",
        "project",
        "goal",
        "progress",
        "next",
        "status",
    ),
    "growth": (
        "学",
        "技能",
        "成长",
        "主题",
        "练习",
        "learn",
        "skill",
        "growth",
        "topic",
        "practice",
    ),
    "timeline": (
        "上周",
        "上个月",
        "这周",
        "本周",
        "今天",
        "最近",
        "发生",
        "回顾",
        "时间线",
        "last week",
        "last month",
        "happened",
        "timeline",
        "recent",
    ),
}

INTENT_TYPES: dict[str, set[str]] = {
    "decision": {"decision", "commitment", "person", "event", "project"},
    "project": {"project", "goal", "task"},
    "growth": {"topic", "skill", "growth_record", "event"},
    "timeline": set(),
}


class QaError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class QaScope:
    source_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    start: datetime | None = None
    end: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_ids": list(self.source_ids),
            "entity_ids": list(self.entity_ids),
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
        }

    @property
    def empty(self) -> bool:
        return not self.source_ids and not self.entity_ids and self.start is None and self.end is None


@dataclass(slots=True)
class _Bucket:
    rows: list[tuple[GraphEvidence, SourceItem, SourceConnection]] = field(default_factory=list)


def _parse_datetime(value: Any, field_name: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise QaError("invalid_scope_date", f"{field_name} must be an ISO-8601 date.", 422) from error
    else:
        raise QaError("invalid_scope_date", f"{field_name} must be an ISO-8601 date.", 422)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def scope_from_dict(raw: dict[str, Any] | None) -> QaScope:
    if not raw:
        return QaScope()
    source_ids = raw.get("source_ids") or []
    entity_ids = raw.get("entity_ids") or []
    if not isinstance(source_ids, list) or not all(isinstance(value, str) for value in source_ids):
        raise QaError("invalid_scope_sources", "source_ids must be a list of strings.", 422)
    if not isinstance(entity_ids, list) or not all(isinstance(value, str) for value in entity_ids):
        raise QaError("invalid_scope_entities", "entity_ids must be a list of strings.", 422)
    if len(source_ids) > 50 or len(entity_ids) > 50:
        raise QaError("scope_too_large", "Choose at most 50 filters per scope.", 413)
    start = _parse_datetime(raw.get("start"), "start")
    end = _parse_datetime(raw.get("end"), "end")
    if start is not None and end is not None and end <= start:
        raise QaError("invalid_scope_range", "The end of the range must be after its start.", 422)
    return QaScope(
        source_ids=tuple(dict.fromkeys(source_ids)),
        entity_ids=tuple(dict.fromkeys(entity_ids)),
        start=start,
        end=end,
    )


def keywords_for(question: str) -> list[str]:
    results: list[str] = []
    for word in WORD_PATTERN.findall(question.lower()):
        if word not in STOPWORDS and len(word) >= 2:
            results.append(word)
    for run in CJK_PATTERN.findall(question):
        if 2 <= len(run) <= 8:
            results.append(run)
        for index in range(len(run) - 1):
            gram = run[index : index + 2]
            if gram not in STOPWORDS:
                results.append(gram)
    return list(dict.fromkeys(results))[:12]


def detect_intent(question: str) -> str | None:
    lowered = question.casefold()
    for intent, words in INTENT_WORDS.items():
        if any(word in lowered for word in words):
            return intent
    return None


def _inferred_range(question: str, scope: QaScope, now: datetime) -> QaScope:
    if scope.start is not None or scope.end is not None:
        return scope
    if "上个月" not in question and "last month" not in question.casefold():
        if "上周" not in question and "last week" not in question.casefold():
            if detect_intent(question) != "timeline":
                return scope
            start = now - timedelta(days=14)
        else:
            start = now - timedelta(days=7)
    else:
        start = now - timedelta(days=30)
    return QaScope(
        source_ids=scope.source_ids,
        entity_ids=scope.entity_ids,
        start=start,
        end=now,
    )


def _scope_relation_ids(session: Session, *, owner_id: str, entity_ids: tuple[str, ...]) -> list[str]:
    if not entity_ids:
        return []
    return list(
        session.scalars(
            select(GraphRelation.id).where(
                GraphRelation.owner_id == owner_id,
                or_(
                    GraphRelation.from_entity_id.in_(entity_ids),
                    GraphRelation.to_entity_id.in_(entity_ids),
                ),
            )
        )
    )


def _evidence_rows(
    session: Session, *, owner_id: str, scope: QaScope
) -> list[tuple[GraphEvidence, SourceItem, SourceConnection, GraphEntity | None, GraphRelation | None]]:
    conditions = [
        GraphEvidence.owner_id == owner_id,
        GraphEvidence.availability == "active",
        SourceItem.owner_id == owner_id,
        SourceItem.deleted_at.is_(None),
        SourceItem.is_current.is_(True),
        SourceConnection.owner_id == owner_id,
        SourceConnection.status.in_(("active", "paused")),
        or_(GraphEntity.id.is_(None), GraphEntity.status == "active"),
        or_(GraphRelation.id.is_(None), GraphRelation.status == "active"),
    ]
    if scope.source_ids:
        conditions.append(GraphEvidence.source_id.in_(scope.source_ids))
    if scope.start is not None:
        conditions.append(SourceItem.occurred_at >= scope.start)
    if scope.end is not None:
        conditions.append(SourceItem.occurred_at < scope.end)
    if scope.entity_ids:
        relation_ids = _scope_relation_ids(session, owner_id=owner_id, entity_ids=scope.entity_ids)
        target = [GraphEvidence.entity_id.in_(scope.entity_ids)]
        if relation_ids:
            target.append(GraphEvidence.relation_id.in_(relation_ids))
        conditions.append(or_(*target))
    rows = session.execute(
        select(GraphEvidence, SourceItem, SourceConnection, GraphEntity, GraphRelation)
        .join(SourceItem, SourceItem.id == GraphEvidence.source_item_id)
        .join(SourceConnection, SourceConnection.id == GraphEvidence.source_id)
        .outerjoin(GraphEntity, GraphEntity.id == GraphEvidence.entity_id)
        .outerjoin(GraphRelation, GraphRelation.id == GraphEvidence.relation_id)
        .where(*conditions)
        .order_by(GraphEvidence.created_at.desc(), GraphEvidence.id)
        .limit(MAX_EVIDENCE_ROWS)
    ).all()
    return [tuple(row) for row in rows]


def _score_row(
    row: tuple[GraphEvidence, SourceItem, SourceConnection, GraphEntity | None, GraphRelation | None],
    keywords: list[str],
    intent: str | None,
) -> int:
    evidence, item, _, entity, _ = row
    text_parts = [item.title, evidence.quote]
    if entity is not None:
        text_parts.extend([entity.name, entity.summary or ""])
    text = " ".join(part for part in text_parts if part).casefold()
    score = sum(2 for keyword in keywords if keyword in text)
    if intent and entity is not None and entity.entity_type in INTENT_TYPES.get(intent, set()):
        score += 3
    return score


def _citation(row: tuple[GraphEvidence, SourceItem, SourceConnection, GraphEntity | None, GraphRelation | None]) -> dict[str, Any]:
    evidence, item, source, _, _ = row
    return {
        "evidence_id": evidence.id,
        "quote": evidence.quote,
        "confidence": round(float(evidence.confidence), 3),
        "availability": evidence.availability,
        "source_id": evidence.source_id,
        "source_name": source.name,
        "source_item_id": evidence.source_item_id,
        "item_title": item.title,
        "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        "locator": evidence.locator,
    }


def _timeline_matches(
    session: Session,
    *,
    owner_id: str,
    scope: QaScope,
    keywords: list[str],
) -> list[dict[str, Any]]:
    conditions = [
        SourceItem.owner_id == owner_id,
        SourceItem.deleted_at.is_(None),
        SourceItem.is_current.is_(True),
        SourceConnection.owner_id == owner_id,
        SourceConnection.status.in_(("active", "paused")),
    ]
    if scope.source_ids:
        conditions.append(SourceItem.source_id.in_(scope.source_ids))
    if scope.start is not None:
        conditions.append(SourceItem.occurred_at >= scope.start)
    if scope.end is not None:
        conditions.append(SourceItem.occurred_at < scope.end)
    if keywords:
        conditions.append(
            or_(
                *[
                    or_(
                        SourceItem.title.icontains(keyword),
                        SourceItem.content_text.icontains(keyword),
                    )
                    for keyword in keywords[:8]
                ]
            )
        )
    rows = session.execute(
        select(SourceItem, SourceConnection)
        .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
        .where(*conditions)
        .order_by(SourceItem.occurred_at.desc(), SourceItem.created_at.desc())
        .limit(MAX_TIMELINE_MATCHES)
    ).all()
    return [
        {
            "source_item_id": item.id,
            "source_id": item.source_id,
            "source_name": source.name,
            "title": item.title,
            "snippet": item.content_text[:180],
            "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
            "kind": item.kind,
        }
        for item, source in rows
    ]


def _review_matches(
    session: Session,
    *,
    owner_id: str,
    scope: QaScope,
    keywords: list[str],
) -> list[dict[str, Any]]:
    conditions = [Review.owner_id == owner_id, Review.status != "invalidated"]
    if scope.start is not None:
        conditions.append(Review.period_end >= scope.start)
    if scope.end is not None:
        conditions.append(Review.period_start < scope.end)
    reviews = list(
        session.scalars(
            select(Review).where(*conditions).order_by(Review.period_start.desc()).limit(20)
        )
    )
    matches: list[dict[str, Any]] = []
    for review in reviews:
        draft = json.dumps(review.draft_json or {}, ensure_ascii=False)
        text = ((review.final_text or "") + " " + draft).casefold()
        if keywords and not any(keyword in text for keyword in keywords):
            continue
        snippet = (review.final_text or draft).strip().replace("\n", " ")[:180]
        matches.append(
            {
                "id": review.id,
                "period_start": review.period_start.isoformat(),
                "period_end": review.period_end.isoformat(),
                "status": review.status,
                "snippet": snippet,
            }
        )
        if len(matches) >= MAX_REVIEW_MATCHES:
            break
    return matches


def _relation_endpoints(
    session: Session, *, owner_id: str, relation_ids: list[str]
) -> dict[str, GraphEntity]:
    if not relation_ids:
        return {}
    return {
        entity.id: entity
        for entity in session.scalars(
            select(GraphEntity).where(
                GraphEntity.owner_id == owner_id,
                GraphEntity.id.in_(
                    select(GraphRelation.from_entity_id)
                    .where(GraphRelation.id.in_(relation_ids))
                    .union(
                        select(GraphRelation.to_entity_id).where(
                            GraphRelation.id.in_(relation_ids)
                        )
                    )
                ),
            )
        )
    }


def _fact_list(
    *,
    entity_buckets: dict[str, _Bucket],
    relation_buckets: dict[str, _Bucket],
    entities: dict[str, GraphEntity],
    relations: dict[str, GraphRelation],
    endpoints: dict[str, GraphEntity],
    threshold: float,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for entity_id, bucket in entity_buckets.items():
        entity = entities.get(entity_id)
        if entity is None:
            continue
        confidence = max(row[0].confidence for row in bucket.rows)
        citation_ids = [row[0].id for row in bucket.rows[:3]]
        facts.append(
            {
                "label": entity.name,
                "detail": entity.summary or f"{entity.entity_type} · {len(bucket.rows)} 条证据",
                "basis": "fact" if confidence >= threshold else "uncertain",
                "confidence": round(float(confidence), 3),
                "entity_id": entity.id,
                "relation_id": None,
                "citation_ids": citation_ids,
            }
        )
    for relation_id, bucket in relation_buckets.items():
        relation = relations.get(relation_id)
        if relation is None:
            continue
        source = endpoints.get(relation.from_entity_id)
        target = endpoints.get(relation.to_entity_id)
        confidence = max(row[0].confidence for row in bucket.rows)
        facts.append(
            {
                "label": " → ".join(
                    part
                    for part in (
                        source.name if source else relation.from_entity_id,
                        relation.relation_type,
                        target.name if target else relation.to_entity_id,
                    )
                ),
                "detail": f"关系证据 {len(bucket.rows)} 条",
                "basis": "inference" if confidence >= threshold else "uncertain",
                "confidence": round(float(confidence), 3),
                "entity_id": None,
                "relation_id": relation.id,
                "citation_ids": [row[0].id for row in bucket.rows[:3]],
            }
        )
    facts.sort(key=lambda fact: fact["confidence"], reverse=True)
    return facts[:MAX_FACTS]


def _suggestions(
    facts: list[dict[str, Any]],
    entities: dict[str, GraphEntity],
    citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(label: str, kind: str, *, entity_id: str | None = None, source_item_id: str | None = None) -> None:
        if label in seen or len(suggestions) >= 4:
            return
        seen.add(label)
        suggestions.append(
            {
                "label": label,
                "kind": kind,
                "entity_id": entity_id,
                "source_item_id": source_item_id,
            }
        )

    types = {entity.entity_type for entity in entities.values()}
    for fact in facts:
        entity = entities.get(fact.get("entity_id") or "")
        if entity is None:
            continue
        if entity.entity_type in ("project", "goal", "task"):
            add("查看项目目标证据并更新下一步", "review", entity_id=entity.id)
        elif entity.entity_type == "commitment":
            add("为这条承诺创建提醒", "reminder", entity_id=entity.id)
        elif entity.entity_type == "decision":
            add("复核决定相关原文", "open_source", entity_id=entity.id)
        elif entity.entity_type in ("skill", "growth_record"):
            add("补充技能练习或成长证据", "review", entity_id=entity.id)
        elif entity.entity_type == "topic":
            add("按这个主题继续追问", "review", entity_id=entity.id)
    if types and citations:
        add("打开原文核对引用", "open_source", source_item_id=citations[0]["source_item_id"])
    return suggestions


def answer_question(
    session: Session,
    *,
    owner_id: str,
    question: str,
    scope: QaScope | None = None,
    threshold: float = 0.75,
    now: datetime | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    current = now or utcnow()
    cleaned = " ".join(question.split())
    if not cleaned:
        raise QaError("question_required", "Enter a question.", 422)
    if len(cleaned) > 2000:
        raise QaError("question_too_long", "Keep the question under 2000 characters.", 422)
    effective_scope = _inferred_range(cleaned, scope or QaScope(), current)
    keywords = keywords_for(cleaned)
    intent = detect_intent(cleaned)

    rows = _evidence_rows(session, owner_id=owner_id, scope=effective_scope)
    scored = [(row, _score_row(row, keywords, intent)) for row in rows]
    relevant = [row for row, score in scored if score > 0]
    if not relevant and intent and INTENT_TYPES.get(intent):
        allowed = INTENT_TYPES[intent]
        relevant = [row for row, _ in scored if row[3] is not None and row[3].entity_type in allowed]
    if not relevant and intent == "timeline":
        relevant = [row for row, _ in scored]
    if not relevant:
        relevant = [row for row, score in scored if score > 0][:60]
    else:
        relevant = relevant[:60]

    entity_buckets: dict[str, _Bucket] = {}
    relation_buckets: dict[str, _Bucket] = {}
    relations: dict[str, GraphRelation] = {}
    entities: dict[str, GraphEntity] = {}
    for evidence, item, source, entity, relation in relevant:
        if entity is not None:
            entities[entity.id] = entity
            entity_buckets.setdefault(entity.id, _Bucket()).rows.append((evidence, item, source))
        if relation is not None:
            relations[relation.id] = relation
            relation_buckets.setdefault(relation.id, _Bucket()).rows.append(
                (evidence, item, source)
            )

    endpoints = _relation_endpoints(
        session, owner_id=owner_id, relation_ids=list(relations)
    )
    facts = _fact_list(
        entity_buckets=entity_buckets,
        relation_buckets=relation_buckets,
        entities=entities,
        relations=relations,
        endpoints=endpoints,
        threshold=threshold,
    )

    citations: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for row in sorted(
        relevant,
        key=lambda value: (
            value[0].confidence,
            value[1].occurred_at.timestamp() if value[1].occurred_at else 0,
        ),
        reverse=True,
    ):
        evidence = row[0]
        if evidence.id in seen_evidence:
            continue
        seen_evidence.add(evidence.id)
        citations.append(_citation(row))
        if len(citations) >= MAX_CITATIONS:
            break
    if not facts:
        citations = []

    timeline_keywords = [] if intent == "timeline" else keywords
    timeline = _timeline_matches(
        session, owner_id=owner_id, scope=effective_scope, keywords=timeline_keywords
    )
    reviews = _review_matches(
        session, owner_id=owner_id, scope=effective_scope, keywords=timeline_keywords
    )

    missing_info: list[str] = []
    if not facts:
        missing_info.append("图谱中没有可用的有效证据；请导入来源并完成抽取。")
        if not effective_scope.empty:
            missing_info.append("当前检索范围内没有有效证据，可清空范围后重试。")
    else:
        if not any(fact["relation_id"] for fact in facts):
            missing_info.append("没有找到实体之间的关系证据，结论可能不完整。")
        if max((fact["confidence"] for fact in facts), default=0) < threshold:
            missing_info.append("最高置信度低于审核阈值，请打开引用核对原文。")
        if any(citation["occurred_at"] is None for citation in citations):
            missing_info.append("部分证据没有时间信息。")

    confidence = max((fact["confidence"] for fact in facts), default=0.0)
    if facts:
        names = [fact["label"] for fact in facts[:4]]
        summary = (
            f"根据 {len(citations)} 条有效证据，找到与问题相关的："
            + "、".join(names)
            + "。以下结论均可回到原文核对。"
        )
        status = "answered"
    else:
        summary = "没有找到可靠证据来回答这个问题。"
        status = "insufficient_evidence"

    return {
        "status": status,
        "summary": summary,
        "facts": facts,
        "citations": citations,
        "timeline_matches": timeline,
        "review_matches": reviews,
        "missing_info": missing_info,
        "suggestions": _suggestions(facts, entities, citations),
        "confidence": round(confidence, 3),
        "scope": effective_scope.as_dict(),
        "keywords": keywords,
        "intent": intent,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "version": QA_VERSION,
    }
