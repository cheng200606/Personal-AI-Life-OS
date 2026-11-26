"""Create, edit, and delete user-authored quick notes."""

from fastapi import APIRouter, HTTPException, Request, Response

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    QuickNoteCreateRequest,
    QuickNoteUpdateRequest,
    SourceItemResponse,
)
from personal_ai_life_os.services.quick_notes import (
    QuickNoteNotFound,
    create_quick_note,
    delete_quick_note,
    update_quick_note,
)
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(prefix="/quick-notes", tags=["quick-notes"])


@router.post("", response_model=SourceItemResponse, status_code=201)
def create_note(
    payload: QuickNoteCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    try:
        return create_quick_note(session, user.id, payload)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "quick_notes_unavailable", "message": str(error)},
        ) from error


@router.patch("/{item_id}", response_model=SourceItemResponse)
def update_note(
    item_id: str,
    payload: QuickNoteUpdateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    try:
        return update_quick_note(session, user.id, item_id, payload)
    except QuickNoteNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "quick_note_not_found", "message": "The selected quick note was not found."},
        ) from error


@router.delete("/{item_id}", status_code=204)
def delete_note(
    item_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    store: ObjectStore = request.app.state.object_store
    try:
        delete_quick_note(session, store, user.id, item_id)
    except QuickNoteNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "quick_note_not_found", "message": "The selected quick note was not found."},
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "deletion_journal_pending",
                "message": "The deletion could not be completed. Retry shortly.",
            },
        ) from error
    return Response(status_code=204)
