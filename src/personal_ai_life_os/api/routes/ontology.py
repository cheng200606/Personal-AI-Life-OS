"""Owner-scoped custom ontology proposals and approvals."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    OntologyTypeCreateRequest,
    OntologyTypeListResponse,
    OntologyTypeResponse,
    OntologyTypeStatusRequest,
)
from personal_ai_life_os.models import OntologyType
from personal_ai_life_os.services.ontology import (
    OntologyError,
    create_type,
    list_types,
    set_status,
)

router = APIRouter(prefix="/ontology", tags=["graph"])


def _error(error: OntologyError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.get("/types", response_model=OntologyTypeListResponse)
def ontology_types(
    user: CurrentUserDep,
    session: SessionDep,
    kind: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
) -> OntologyTypeListResponse:
    conditions = [OntologyType.owner_id == user.id]
    if kind:
        conditions.append(OntologyType.kind == kind)
    if status:
        conditions.append(OntologyType.status == status)
    total = session.scalar(
        select(func.count()).select_from(
            select(OntologyType.id).where(*conditions).subquery()
        )
    ) or 0
    return OntologyTypeListResponse(
        total=total,
        items=[
            OntologyTypeResponse.model_validate(entry, from_attributes=True)
            for entry in list_types(session, owner_id=user.id, kind=kind, status=status)
        ],
    )


@router.post("/types", response_model=OntologyTypeResponse, status_code=201)
def create_ontology_type(
    payload: OntologyTypeCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> OntologyTypeResponse:
    try:
        entry = create_type(
            session,
            owner_id=user.id,
            kind=payload.kind,
            name=payload.name,
            description=payload.description,
            source="user",
            created_by="user",
        )
    except OntologyError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(entry)
    return OntologyTypeResponse.model_validate(entry, from_attributes=True)


@router.post("/types/{type_id}/decision", response_model=OntologyTypeResponse)
def decide_ontology_type(
    type_id: str,
    payload: OntologyTypeStatusRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> OntologyTypeResponse:
    try:
        entry = set_status(
            session,
            owner_id=user.id,
            type_id=type_id,
            status=payload.status,
        )
    except OntologyError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(entry)
    return OntologyTypeResponse.model_validate(entry, from_attributes=True)
