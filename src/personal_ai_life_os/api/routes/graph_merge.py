"""Manual merges and undo for graph entities."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    GraphMergeListResponse,
    GraphMergeRequest,
    GraphMergeResponse,
)
from personal_ai_life_os.models import EntityMergeLog
from personal_ai_life_os.services.graph_merges import (
    GraphMergeError,
    list_merges,
    merge_entities,
    merge_log_payload,
    undo_merge,
)

router = APIRouter(prefix="/graph", tags=["graph"])


def _error(error: GraphMergeError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.post("/entities/{entity_id}/merge", response_model=GraphMergeResponse, status_code=201)
def merge_graph_entities(
    entity_id: str,
    payload: GraphMergeRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> GraphMergeResponse:
    try:
        log = merge_entities(
            session,
            owner_id=user.id,
            source_entity_id=entity_id,
            target_entity_id=payload.target_entity_id,
            merged_by="user",
        )
    except GraphMergeError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(log)
    return GraphMergeResponse(**merge_log_payload(log))


@router.get("/merges", response_model=GraphMergeListResponse)
def merge_history(
    user: CurrentUserDep,
    session: SessionDep,
) -> GraphMergeListResponse:
    total = session.scalar(
        select(func.count()).select_from(
            select(EntityMergeLog.id).where(EntityMergeLog.owner_id == user.id).subquery()
        )
    ) or 0
    return GraphMergeListResponse(
        total=total,
        items=[
            GraphMergeResponse(**merge_log_payload(log))
            for log in list_merges(session, owner_id=user.id)
        ],
    )


@router.post("/merges/{merge_id}/undo", response_model=GraphMergeResponse)
def undo_graph_merge(
    merge_id: str,
    user: CurrentUserDep,
    session: SessionDep,
) -> GraphMergeResponse:
    try:
        log = undo_merge(session, owner_id=user.id, merge_id=merge_id)
    except GraphMergeError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(log)
    return GraphMergeResponse(**merge_log_payload(log))
