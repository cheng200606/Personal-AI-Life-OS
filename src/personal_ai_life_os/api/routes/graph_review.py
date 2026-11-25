"""Owner-scoped review queue for low-confidence graph changes."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    GraphReviewBulkRequest,
    GraphReviewDecisionRequest,
    GraphReviewItemResponse,
    GraphReviewListResponse,
    GraphReviewUpdateRequest,
)
from personal_ai_life_os.models import GraphReviewItem
from personal_ai_life_os.services.graph_review import (
    GraphReviewError,
    item_payload,
    list_items,
    resolve_bulk,
    resolve_item,
    update_item,
)

router = APIRouter(prefix="/graph/review", tags=["graph"])


def _error(error: GraphReviewError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.get("", response_model=GraphReviewListResponse)
def review_queue(
    user: CurrentUserDep,
    session: SessionDep,
    status: Annotated[str | None, Query(max_length=24)] = "pending",
    kind: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> GraphReviewListResponse:
    conditions = [GraphReviewItem.owner_id == user.id]
    if status:
        conditions.append(GraphReviewItem.status == status)
    if kind:
        conditions.append(GraphReviewItem.kind == kind)
    total = session.scalar(
        select(func.count()).select_from(
            select(GraphReviewItem.id).where(*conditions).subquery()
        )
    ) or 0
    items = list_items(session, owner_id=user.id, status=status, kind=kind, limit=limit)
    return GraphReviewListResponse(
        total=total,
        items=[GraphReviewItemResponse(**item_payload(item)) for item in items],
    )


@router.post("/bulk", response_model=GraphReviewListResponse)
def resolve_review_bulk(
    payload: GraphReviewBulkRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> GraphReviewListResponse:
    try:
        items = resolve_bulk(
            session,
            owner_id=user.id,
            item_ids=payload.item_ids,
            action=payload.action,
        )
    except GraphReviewError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    return GraphReviewListResponse(
        total=len(items),
        items=[GraphReviewItemResponse(**item_payload(item)) for item in items],
    )


@router.patch("/{item_id}", response_model=GraphReviewItemResponse)
def edit_review_item(
    item_id: str,
    payload: GraphReviewUpdateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> GraphReviewItemResponse:
    try:
        item = update_item(
            session,
            owner_id=user.id,
            item_id=item_id,
            name=payload.name,
            entity_type=payload.entity_type,
            relation_type=payload.relation_type,
            summary=payload.summary,
            confidence=payload.confidence,
        )
    except GraphReviewError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(item)
    return GraphReviewItemResponse(**item_payload(item))


@router.post("/{item_id}/decision", response_model=GraphReviewItemResponse)
def decide_review_item(
    item_id: str,
    payload: GraphReviewDecisionRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> GraphReviewItemResponse:
    try:
        item = resolve_item(
            session,
            owner_id=user.id,
            item_id=item_id,
            action=payload.action,
        )
    except GraphReviewError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(item)
    return GraphReviewItemResponse(**item_payload(item))
