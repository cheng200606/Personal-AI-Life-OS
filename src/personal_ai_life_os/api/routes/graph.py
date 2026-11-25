"""Owner-scoped graph read endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    GraphEntityListResponse,
    GraphEntityResponse,
    GraphEvidenceResponse,
    GraphRelationListResponse,
    GraphRelationResponse,
)
from personal_ai_life_os.models import GraphEntity, GraphEvidence, GraphRelation

router = APIRouter(prefix="/graph", tags=["graph"])


def _evidence(
    session: Session,
    *,
    owner_id: str,
    entity_id: str | None = None,
    relation_id: str | None = None,
) -> list[GraphEvidenceResponse]:
    conditions = [GraphEvidence.owner_id == owner_id]
    if entity_id is not None:
        conditions.append(GraphEvidence.entity_id == entity_id)
    if relation_id is not None:
        conditions.append(GraphEvidence.relation_id == relation_id)
    rows = list(
        session.scalars(
            select(GraphEvidence)
            .where(*conditions)
            .order_by(GraphEvidence.created_at, GraphEvidence.id)
            .limit(20)
        )
    )
    return [
        GraphEvidenceResponse(
            id=row.id,
            quote=row.quote,
            confidence=row.confidence,
            availability=row.availability,
            source_id=row.source_id,
            source_item_id=row.source_item_id,
            locator=row.locator,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/entities", response_model=GraphEntityListResponse)
def list_entities(
    user: CurrentUserDep,
    session: SessionDep,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> GraphEntityListResponse:
    conditions = [
        GraphEntity.owner_id == user.id,
        GraphEntity.status.in_(("active", "pending_review")),
    ]
    if entity_type:
        conditions.append(GraphEntity.entity_type == entity_type)
    if q and q.strip():
        conditions.append(GraphEntity.name.icontains(q.strip()))
    base = select(GraphEntity).where(*conditions)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    entities = list(
        session.scalars(
            base.order_by(GraphEntity.updated_at.desc(), GraphEntity.id).limit(limit)
        )
    )
    return GraphEntityListResponse(
        total=total,
        items=[
            GraphEntityResponse(
                id=entity.id,
                entity_type=entity.entity_type,
                name=entity.name,
                summary=entity.summary,
                confidence=entity.confidence,
                status=entity.status,
                evidence=_evidence(session, owner_id=user.id, entity_id=entity.id),
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
            for entity in entities
        ],
    )


@router.get("/relations", response_model=GraphRelationListResponse)
def list_relations(
    user: CurrentUserDep,
    session: SessionDep,
    relation_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> GraphRelationListResponse:
    conditions = [
        GraphRelation.owner_id == user.id,
        GraphRelation.status != "invalid",
    ]
    if relation_type:
        conditions.append(GraphRelation.relation_type == relation_type)
    base = select(GraphRelation).where(*conditions)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    relations = list(
        session.scalars(
            base.order_by(GraphRelation.updated_at.desc(), GraphRelation.id).limit(limit)
        )
    )
    return GraphRelationListResponse(
        total=total,
        items=[
            GraphRelationResponse(
                id=relation.id,
                from_entity_id=relation.from_entity_id,
                to_entity_id=relation.to_entity_id,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                status=relation.status,
                evidence=_evidence(session, owner_id=user.id, relation_id=relation.id),
                created_at=relation.created_at,
                updated_at=relation.updated_at,
            )
            for relation in relations
        ],
    )
