"""Approve, reject, and edit low-confidence graph review items."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.models import (
    GraphEntity,
    GraphRelation,
    GraphReviewItem,
    OntologyType,
    utcnow,
)
from personal_ai_life_os.services import ontology
from personal_ai_life_os.services.graph_extraction import (
    CORE_ENTITY_TYPES,
    CORE_RELATION_TYPES,
)
from personal_ai_life_os.services.graph_merges import merge_entities


class GraphReviewError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def list_items(
    session: Session,
    *,
    owner_id: str,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[GraphReviewItem]:
    conditions = [GraphReviewItem.owner_id == owner_id]
    if status:
        conditions.append(GraphReviewItem.status == status)
    if kind:
        conditions.append(GraphReviewItem.kind == kind)
    return list(
        session.scalars(
            select(GraphReviewItem)
            .where(*conditions)
            .order_by(GraphReviewItem.created_at.desc(), GraphReviewItem.id)
            .limit(limit)
        )
    )


def get_item(session: Session, *, owner_id: str, item_id: str) -> GraphReviewItem:
    item = session.scalar(
        select(GraphReviewItem).where(
            GraphReviewItem.id == item_id,
            GraphReviewItem.owner_id == owner_id,
        )
    )
    if item is None:
        raise GraphReviewError("review_item_not_found", "The review item was not found.", 404)
    return item


def _entity(session: Session, owner_id: str, entity_id: str | None) -> GraphEntity | None:
    if not entity_id:
        return None
    entity = session.get(GraphEntity, entity_id)
    if entity is None or entity.owner_id != owner_id:
        return None
    return entity


def _relation(
    session: Session, owner_id: str, relation_id: str | None
) -> GraphRelation | None:
    if not relation_id:
        return None
    relation = session.get(GraphRelation, relation_id)
    if relation is None or relation.owner_id != owner_id:
        return None
    return relation


def _validate_entity_type(session: Session, owner_id: str, entity_type: str) -> str:
    value = entity_type.strip().lower()
    if value in CORE_ENTITY_TYPES:
        return value
    if value in ontology.approved_names(session, owner_id=owner_id, kind="entity"):
        return value
    raise GraphReviewError(
        "unknown_entity_type",
        "Approve this entity type in the ontology list before using it.",
        422,
    )


def _validate_relation_type(session: Session, owner_id: str, relation_type: str) -> str:
    value = relation_type.strip().lower()
    if value in CORE_RELATION_TYPES:
        return value
    if value in ontology.approved_names(session, owner_id=owner_id, kind="relation"):
        return value
    raise GraphReviewError(
        "unknown_relation_type",
        "Approve this relation type in the ontology list before using it.",
        422,
    )


def update_item(
    session: Session,
    *,
    owner_id: str,
    item_id: str,
    name: str | None = None,
    entity_type: str | None = None,
    relation_type: str | None = None,
    summary: str | None = None,
    confidence: float | None = None,
) -> GraphReviewItem:
    item = get_item(session, owner_id=owner_id, item_id=item_id)
    if item.status != "pending":
        raise GraphReviewError("review_item_resolved", "This review item is already resolved.")
    payload = dict(item.payload)

    if item.kind == "entity":
        entity = _entity(session, owner_id, payload.get("entity_id"))
        if entity is None:
            raise GraphReviewError("graph_entity_not_found", "The reviewed entity no longer exists.", 404)
        if name is not None:
            cleaned = name.strip()
            if not cleaned:
                raise GraphReviewError("invalid_entity_name", "Enter an entity name.", 422)
            entity.name = cleaned[:500]
            entity.normalized_name = " ".join(cleaned.split()).casefold()[:500]
            payload["name"] = entity.name
        if entity_type is not None:
            entity.entity_type = _validate_entity_type(session, owner_id, entity_type)
            payload["type"] = entity.entity_type
        if summary is not None:
            entity.summary = summary.strip() or None
            payload["summary"] = entity.summary
        if confidence is not None:
            entity.confidence = confidence
            item.confidence = confidence
            payload["confidence"] = confidence
    elif item.kind == "relation":
        relation = _relation(session, owner_id, payload.get("relation_id"))
        if relation is None:
            raise GraphReviewError(
                "graph_relation_not_found", "The reviewed relation no longer exists.", 404
            )
        if relation_type is not None:
            relation.relation_type = _validate_relation_type(session, owner_id, relation_type)
            payload["relation_type"] = relation.relation_type
        if confidence is not None:
            relation.confidence = confidence
            item.confidence = confidence
            payload["confidence"] = confidence
    else:
        raise GraphReviewError(
            "review_item_not_editable",
            "Only low-confidence entity and relation items can be edited.",
            422,
        )

    item.payload = payload
    session.flush()
    return item


def _approve(
    session: Session, *, owner_id: str, item: GraphReviewItem
) -> None:
    payload = item.payload
    if item.kind == "entity":
        entity = _entity(session, owner_id, payload.get("entity_id"))
        if entity is None:
            raise GraphReviewError("graph_entity_not_found", "The reviewed entity no longer exists.", 404)
        if entity.status not in ("active", "pending_review"):
            raise GraphReviewError(
                "entity_not_approvable", "This entity was merged or rejected and cannot be approved."
            )
        entity.status = "active"
    elif item.kind == "relation":
        relation = _relation(session, owner_id, payload.get("relation_id"))
        if relation is None:
            raise GraphReviewError(
                "graph_relation_not_found", "The reviewed relation no longer exists.", 404
            )
        if relation.status not in ("active", "pending_review"):
            raise GraphReviewError(
                "relation_not_approvable",
                "This relation was rejected and cannot be approved.",
            )
        relation.status = "active"
    elif item.kind == "merge":
        merge_entities(
            session,
            owner_id=owner_id,
            source_entity_id=str(payload.get("source_entity_id") or ""),
            target_entity_id=str(payload.get("target_entity_id") or ""),
            merged_by="user",
        )
    elif item.kind == "ontology":
        ontology.set_status(
            session,
            owner_id=owner_id,
            type_id=str(payload.get("ontology_type_id") or ""),
            status="approved",
        )
    else:
        raise GraphReviewError("unsupported_review_kind", "This review item kind is unsupported.", 422)


def _reject(session: Session, *, owner_id: str, item: GraphReviewItem) -> None:
    payload = item.payload
    if item.kind == "entity":
        entity = _entity(session, owner_id, payload.get("entity_id"))
        if entity is not None and entity.status in ("active", "pending_review"):
            entity.status = "invalid"
    elif item.kind == "relation":
        relation = _relation(session, owner_id, payload.get("relation_id"))
        if relation is not None and relation.status in ("active", "pending_review"):
            relation.status = "invalid"
    elif item.kind == "ontology":
        entry = session.get(OntologyType, str(payload.get("ontology_type_id") or ""))
        if entry is not None and entry.owner_id == owner_id and entry.status == "proposed":
            entry.status = "rejected"
            entry.version += 1
            entry.updated_at = utcnow()


def resolve_item(
    session: Session,
    *,
    owner_id: str,
    item_id: str,
    action: str,
) -> GraphReviewItem:
    if action not in ("approve", "reject"):
        raise GraphReviewError("invalid_review_action", "Choose approve or reject.", 422)
    item = get_item(session, owner_id=owner_id, item_id=item_id)
    if item.status != "pending":
        raise GraphReviewError("review_item_resolved", "This review item is already resolved.")
    if action == "approve":
        _approve(session, owner_id=owner_id, item=item)
        item.status = "approved"
    else:
        _reject(session, owner_id=owner_id, item=item)
        item.status = "rejected"
    item.resolved_at = utcnow()
    session.flush()
    return item


def resolve_bulk(
    session: Session, *, owner_id: str, item_ids: list[str], action: str
) -> list[GraphReviewItem]:
    if not item_ids:
        raise GraphReviewError("review_selection_required", "Choose at least one review item.", 422)
    if len(item_ids) > 200:
        raise GraphReviewError("review_selection_too_large", "Choose at most 200 review items.", 413)
    resolved = [
        resolve_item(session, owner_id=owner_id, item_id=item_id, action=action)
        for item_id in dict.fromkeys(item_ids)
    ]
    return resolved


def item_payload(item: GraphReviewItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "payload": item.payload,
        "confidence": item.confidence,
        "status": item.status,
        "reason": item.reason,
        "extraction_run_id": item.extraction_run_id,
        "created_at": item.created_at,
        "resolved_at": item.resolved_at,
    }
