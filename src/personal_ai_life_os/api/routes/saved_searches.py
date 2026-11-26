"""Owner-scoped saved unified searches."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    SavedSearchCreateRequest,
    SavedSearchResponse,
    SavedSearchUpdateRequest,
    SearchFilters,
)
from personal_ai_life_os.models import SavedSearch

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])


def _response(entry: SavedSearch) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "query": entry.query,
        "filters": SearchFilters.model_validate(entry.filters_json),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _entry_or_404(session: SessionDep, owner_id: str, entry_id: str) -> SavedSearch:
    entry = session.scalar(
        select(SavedSearch).where(SavedSearch.id == entry_id, SavedSearch.owner_id == owner_id)
    )
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "saved_search_not_found", "message": "The selected saved search was not found."},
        )
    return entry


@router.get("", response_model=list[SavedSearchResponse])
def list_saved_searches(user: CurrentUserDep, session: SessionDep) -> list[dict]:
    entries = list(
        session.scalars(
            select(SavedSearch)
            .where(SavedSearch.owner_id == user.id)
            .order_by(SavedSearch.created_at.desc(), SavedSearch.id)
        )
    )
    return [_response(entry) for entry in entries]


@router.post("", response_model=SavedSearchResponse, status_code=201)
def create_saved_search(
    payload: SavedSearchCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    entry = SavedSearch(
        owner_id=user.id,
        name=payload.name,
        name_key=payload.name.casefold(),
        query=payload.query,
        filters_json=payload.filters.model_dump(mode="json"),
    )
    session.add(entry)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "saved_search_exists", "message": "A saved search with this name already exists."},
        ) from error
    session.refresh(entry)
    return _response(entry)


@router.patch("/{entry_id}", response_model=SavedSearchResponse)
def update_saved_search(
    entry_id: str,
    payload: SavedSearchUpdateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    entry = _entry_or_404(session, user.id, entry_id)
    if payload.name is not None:
        entry.name = payload.name
        entry.name_key = payload.name.casefold()
    if payload.filters is not None:
        entry.filters_json = payload.filters.model_dump(mode="json")
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "saved_search_exists", "message": "A saved search with this name already exists."},
        ) from error
    session.refresh(entry)
    return _response(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_saved_search(entry_id: str, user: CurrentUserDep, session: SessionDep) -> None:
    entry = _entry_or_404(session, user.id, entry_id)
    session.delete(entry)
    session.commit()
