"""Owner-scoped agent actions, tool policies, and undo."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    AgentActionCreateRequest,
    AgentActionListResponse,
    AgentActionResponse,
    AgentToolListResponse,
    AgentToolResponse,
)
from personal_ai_life_os.models import AgentAction
from personal_ai_life_os.services.agent_actions import (
    AgentActionError,
    action_payload,
    create_action,
    list_actions,
    list_tools,
    undo_action,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/tools", response_model=AgentToolListResponse)
def agent_tools(user: CurrentUserDep) -> AgentToolListResponse:
    items = [AgentToolResponse(**tool) for tool in list_tools()]
    return AgentToolListResponse(total=len(items), items=items)


@router.get("/actions", response_model=AgentActionListResponse)
def agent_action_list(
    user: CurrentUserDep,
    session: SessionDep,
    status: Annotated[str | None, Query(max_length=24)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AgentActionListResponse:
    conditions = [AgentAction.owner_id == user.id]
    if status:
        conditions.append(AgentAction.status == status)
    total = session.scalar(
        select(func.count()).select_from(
            select(AgentAction.id).where(*conditions).subquery()
        )
    ) or 0
    return AgentActionListResponse(
        total=total,
        items=[
            AgentActionResponse(**action_payload(action))
            for action in list_actions(session, owner_id=user.id, status=status, limit=limit)
        ],
    )


@router.post("/actions", response_model=AgentActionResponse, status_code=201)
def create_agent_action(
    payload: AgentActionCreateRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> AgentActionResponse:
    try:
        action = create_action(
            session,
            owner_id=user.id,
            kind=payload.kind,
            payload=payload.payload,
            config=request.app.state.settings,
            approved=payload.approved,
        )
    except AgentActionError as error:
        if error.action is not None:
            session.commit()
        else:
            session.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    session.commit()
    session.refresh(action)
    return AgentActionResponse(**action_payload(action))


@router.post("/actions/{action_id}/undo", response_model=AgentActionResponse)
def undo_agent_action(
    action_id: str,
    user: CurrentUserDep,
    session: SessionDep,
) -> AgentActionResponse:
    try:
        action = undo_action(session, owner_id=user.id, action_id=action_id)
    except AgentActionError as error:
        if error.action is not None:
            session.commit()
        else:
            session.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    session.commit()
    session.refresh(action)
    return AgentActionResponse(**action_payload(action))
