"""Reversible merges for high-confidence duplicate graph entities."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from personal_ai_life_os.models import (
    EntityAlias,
    EntityMergeLog,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    GraphReviewItem,
    utcnow,
)

MERGED_STATUSES = ("active", "pending_review")


class GraphMergeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _normalize_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _entity_or_404(session: Session, owner_id: str, entity_id: str) -> GraphEntity:
    entity = session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == entity_id,
            GraphEntity.owner_id == owner_id,
        )
    )
    if entity is None:
        raise GraphMergeError("graph_entity_not_found", "The selected entity was not found.", 404)
    return entity


def _entity_snapshot(entity: GraphEntity) -> dict[str, Any]:
    return {
        "id": entity.id,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "normalized_name": entity.normalized_name,
        "summary": entity.summary,
        "confidence": entity.confidence,
        "status": entity.status,
        "merged_into_id": entity.merged_into_id,
    }


def _relation_snapshot(relation: GraphRelation) -> dict[str, Any]:
    return {
        "id": relation.id,
        "from_entity_id": relation.from_entity_id,
        "to_entity_id": relation.to_entity_id,
        "status": relation.status,
    }


def _ensure_target_alias(
    session: Session, *, owner_id: str, target: GraphEntity, name: str
) -> str | None:
    normalized = _normalize_name(name)
    if not normalized:
        return None
    existing = session.scalar(
        select(EntityAlias.id).where(
            EntityAlias.owner_id == owner_id,
            EntityAlias.entity_id == target.id,
            EntityAlias.normalized_alias == normalized,
        )
    )
    if existing is not None:
        return None
    alias = EntityAlias(
        owner_id=owner_id,
        entity_id=target.id,
        alias=name[:500],
        normalized_alias=normalized,
    )
    session.add(alias)
    session.flush()
    return alias.id


def merge_entities(
    session: Session,
    *,
    owner_id: str,
    source_entity_id: str,
    target_entity_id: str,
    merged_by: str = "user",
) -> EntityMergeLog:
    """Merge one entity into another while keeping a full undo snapshot."""
    if source_entity_id == target_entity_id:
        raise GraphMergeError(
            "merge_requires_two_entities", "Choose two different entities to merge.", 422
        )
    source = _entity_or_404(session, owner_id, source_entity_id)
    target = _entity_or_404(session, owner_id, target_entity_id)
    if source.status not in MERGED_STATUSES:
        raise GraphMergeError(
            "entity_not_mergeable", "This entity has already been merged or rejected."
        )
    if target.status not in MERGED_STATUSES:
        raise GraphMergeError("entity_not_mergeable", "The target entity is not active.")

    entity_before = _entity_snapshot(source)
    aliases = list(
        session.scalars(
            select(EntityAlias).where(
                EntityAlias.owner_id == owner_id,
                EntityAlias.entity_id == source.id,
            )
        )
    )
    alias_snapshots = [
        {
            "id": alias.id,
            "alias": alias.alias,
            "normalized_alias": alias.normalized_alias,
        }
        for alias in aliases
    ]
    evidence_ids = list(
        session.scalars(
            select(GraphEvidence.id).where(
                GraphEvidence.owner_id == owner_id,
                GraphEvidence.entity_id == source.id,
            )
        )
    )
    relations = list(
        session.scalars(
            select(GraphRelation).where(
                GraphRelation.owner_id == owner_id,
                (GraphRelation.from_entity_id == source.id)
                | (GraphRelation.to_entity_id == source.id),
            )
        )
    )
    relation_snapshots = [_relation_snapshot(relation) for relation in relations]
    affected_reviews = [
        item
        for item in session.scalars(
            select(GraphReviewItem).where(
                GraphReviewItem.owner_id == owner_id,
                GraphReviewItem.status == "pending",
            )
        )
        if item.payload.get("entity_id") == source.id
    ]
    created_alias_id = _ensure_target_alias(
        session, owner_id=owner_id, target=target, name=source.name
    )

    for alias in aliases:
        alias.entity_id = target.id
    if evidence_ids:
        session.execute(
            update(GraphEvidence)
            .where(GraphEvidence.owner_id == owner_id, GraphEvidence.id.in_(evidence_ids))
            .values(entity_id=target.id)
        )
    for relation in relations:
        if relation.from_entity_id == source.id:
            relation.from_entity_id = target.id
        if relation.to_entity_id == source.id:
            relation.to_entity_id = target.id
        if relation.from_entity_id == relation.to_entity_id:
            relation.status = "invalid"
    for review in affected_reviews:
        review.status = "superseded"
        review.resolved_at = utcnow()

    source.status = "merged"
    source.merged_into_id = target.id

    log = EntityMergeLog(
        owner_id=owner_id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        status="active",
        snapshot={
            "merged_by": merged_by,
            "entity": entity_before,
            "target_name": target.name,
            "aliases": alias_snapshots,
            "created_alias_id": created_alias_id,
            "evidence_ids": evidence_ids,
            "relations": relation_snapshots,
            "review_items": [
                {"id": review.id, "status": "pending"} for review in affected_reviews
            ],
        },
    )
    session.add(log)
    session.flush()
    return log


def undo_merge(session: Session, *, owner_id: str, merge_id: str) -> EntityMergeLog:
    log = session.scalar(
        select(EntityMergeLog).where(
            EntityMergeLog.id == merge_id,
            EntityMergeLog.owner_id == owner_id,
        )
    )
    if log is None:
        raise GraphMergeError("merge_not_found", "The merge record was not found.", 404)
    if log.status != "active":
        raise GraphMergeError("merge_already_undone", "This merge has already been undone.")

    snapshot = log.snapshot or {}
    entity_state = snapshot.get("entity") or {}
    source = None
    entity_id = entity_state.get("id")
    if entity_id:
        source = session.scalar(
            select(GraphEntity).where(
                GraphEntity.id == entity_id,
                GraphEntity.owner_id == owner_id,
            )
        )
    if source is None:
        raise GraphMergeError(
            "merge_source_missing",
            "The merged entity no longer exists, so this merge cannot be undone.",
        )

    source.name = str(entity_state.get("name") or source.name)[:500]
    source.entity_type = str(entity_state.get("entity_type") or source.entity_type)[:64]
    source.normalized_name = str(
        entity_state.get("normalized_name") or source.normalized_name
    )[:500]
    source.summary = entity_state.get("summary")
    source.confidence = float(entity_state.get("confidence") or source.confidence)
    source.status = str(entity_state.get("status") or "active")
    source.merged_into_id = entity_state.get("merged_into_id")

    for alias_state in snapshot.get("aliases", []):
        alias = session.get(EntityAlias, alias_state.get("id"))
        if alias is not None and alias.owner_id == owner_id:
            alias.entity_id = source.id

    created_alias_id = snapshot.get("created_alias_id")
    if created_alias_id:
        created_alias = session.get(EntityAlias, created_alias_id)
        if created_alias is not None and created_alias.owner_id == owner_id:
            session.delete(created_alias)

    evidence_ids = snapshot.get("evidence_ids") or []
    if evidence_ids:
        session.execute(
            update(GraphEvidence)
            .where(GraphEvidence.owner_id == owner_id, GraphEvidence.id.in_(evidence_ids))
            .values(entity_id=source.id)
        )
    for relation_state in snapshot.get("relations", []):
        relation = session.get(GraphRelation, relation_state.get("id"))
        if relation is None or relation.owner_id != owner_id:
            continue
        relation.from_entity_id = relation_state.get("from_entity_id")
        relation.to_entity_id = relation_state.get("to_entity_id")
        relation.status = str(relation_state.get("status") or "active")
    for review_state in snapshot.get("review_items", []):
        review = session.get(GraphReviewItem, review_state.get("id"))
        if review is not None and review.owner_id == owner_id:
            review.status = str(review_state.get("status") or "pending")
            review.resolved_at = None

    log.status = "undone"
    log.undone_at = utcnow()
    session.flush()
    return log


def list_merges(session: Session, *, owner_id: str, limit: int = 50) -> list[EntityMergeLog]:
    return list(
        session.scalars(
            select(EntityMergeLog)
            .where(EntityMergeLog.owner_id == owner_id)
            .order_by(EntityMergeLog.created_at.desc(), EntityMergeLog.id)
            .limit(limit)
        )
    )


def merge_log_payload(log: EntityMergeLog) -> dict[str, Any]:
    snapshot = log.snapshot or {}
    entity_state = snapshot.get("entity") or {}
    return {
        "id": log.id,
        "source_entity_id": log.source_entity_id,
        "target_entity_id": log.target_entity_id,
        "source_name": entity_state.get("name"),
        "target_name": snapshot.get("target_name"),
        "status": log.status,
        "evidence_count": len(snapshot.get("evidence_ids") or []),
        "relation_count": len(snapshot.get("relations") or []),
        "created_at": log.created_at,
        "undone_at": log.undone_at,
    }
