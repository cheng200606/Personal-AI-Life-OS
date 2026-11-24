"""Source connection management and authorized source downloads."""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    SourceCreateRequest,
    SourceResponse,
    SourceScopeRequest,
    SourceStatusRequest,
    SyncRunResponse,
)
from personal_ai_life_os.models import (
    SourceConnection,
    SourceItem,
    SyncRun,
)
from personal_ai_life_os.services.deletion import (
    complete_source_deletion,
    request_source_deletion,
    scrub_source_derivatives,
)
from personal_ai_life_os.services.jobs import cancel_jobs_for_source
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(tags=["sources"])


def _source_or_404(session: SessionDep, source_id: str, owner_id: str) -> SourceConnection:
    source = session.scalar(
        select(SourceConnection).where(
            SourceConnection.id == source_id,
            SourceConnection.owner_id == owner_id,
        )
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "source_not_found", "message": "The selected source was not found."},
        )
    return source


@router.post("/sources", response_model=SourceResponse, status_code=201)
def create_source(
    payload: SourceCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> SourceConnection:
    source = SourceConnection(
        owner_id=user.id,
        kind=payload.kind,
        name=payload.name.strip(),
        status="active",
        consent_version=payload.consent_version,
        selected_scope=payload.selected_scope,
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(user: CurrentUserDep, session: SessionDep) -> list[SourceConnection]:
    return list(
        session.scalars(
            select(SourceConnection)
            .where(
                SourceConnection.owner_id == user.id,
                SourceConnection.status != "deleting",
            )
            .order_by(SourceConnection.created_at.desc(), SourceConnection.id)
        )
    )


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: str,
    user: CurrentUserDep,
    session: SessionDep,
) -> SourceConnection:
    source = _source_or_404(session, source_id, user.id)
    if source.status == "deleting":
        raise HTTPException(
            status_code=404,
            detail={"code": "source_not_found", "message": "The selected source was not found."},
        )
    return source


@router.patch("/sources/{source_id}/status", response_model=SourceResponse)
def update_source_status(
    source_id: str,
    payload: SourceStatusRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> SourceConnection:
    source = _source_or_404(session, source_id, user.id)
    if source.status not in {"active", "paused"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_cannot_resume",
                "message": "A disconnected or deleting source cannot be resumed. Create a new source selection.",
            },
        )
    source.status = payload.status
    if payload.status == "paused":
        cancel_jobs_for_source(session, source.id, reason="source_paused")
    session.commit()
    session.refresh(source)
    return source


@router.patch("/sources/{source_id}/scope", response_model=SourceResponse)
def update_source_scope(
    source_id: str,
    payload: SourceScopeRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> SourceConnection:
    source = _source_or_404(session, source_id, user.id)
    if source.status != "active":
        raise HTTPException(
            status_code=409,
            detail={"code": "source_not_active", "message": "Resume this source before changing its selection."},
        )
    if source.kind == "chatgpt_export" and "conversation_ids" not in payload.selected_scope:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "conversation_selection_required",
                "message": "A ChatGPT source must include the selected conversation IDs.",
            },
        )
    source.selected_scope = payload.selected_scope
    source.consent_version = payload.consent_version
    session.commit()
    session.refresh(source)
    return source


@router.post("/sources/{source_id}/revoke", response_model=SourceResponse)
def revoke_source(
    source_id: str,
    user: CurrentUserDep,
    session: SessionDep,
) -> SourceConnection:
    source = _source_or_404(session, source_id, user.id)
    if source.status == "deleting":
        raise HTTPException(
            status_code=409,
            detail={"code": "source_deleting", "message": "This source is being deleted."},
        )
    source.status = "revoked"
    cancel_jobs_for_source(session, source.id, reason="source_revoked")
    session.commit()
    session.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    source = _source_or_404(session, source_id, user.id)
    store: ObjectStore = request.app.state.object_store
    try:
        tombstone = request_source_deletion(store, user.id, source_id)
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "source_tombstone_pending", "message": "Deletion could not be durably recorded. Source data remains available; retry shortly."},
        ) from error
    source.status = "deleting"
    cancel_jobs_for_source(session, source.id, reason="source_deleting")
    session.commit()

    items = scrub_source_derivatives(session, user.id, source_id)

    keys = {item.object_key for item in items if item.object_key}
    keys.update(
        session.scalars(
            select(SyncRun.object_key).where(
                SyncRun.source_id == source_id,
                SyncRun.owner_id == user.id,
                SyncRun.object_key.is_not(None),
            )
        )
    )
    try:
        for key in keys:
            if key:
                store.delete(key)
        store.delete_source_objects(user.id, source_id)
        complete_source_deletion(store, user.id, source_id, tombstone)
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "source_cleanup_pending",
                "message": "Access is blocked while source cleanup retries. Repeat this request to retry cleanup.",
            },
        ) from error

    session.delete(source)
    session.commit()
    return Response(status_code=204)


@router.get("/sync-runs", response_model=list[SyncRunResponse])
def list_sync_runs(
    user: CurrentUserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[SyncRun]:
    return list(
        session.scalars(
            select(SyncRun)
            .where(SyncRun.owner_id == user.id)
            .order_by(SyncRun.created_at.desc(), SyncRun.id)
            .limit(limit)
        )
    )


@router.get("/items/{item_id}/raw")
def download_source_item(
    item_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> StreamingResponse:
    item = session.scalar(
        select(SourceItem)
        .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
        .where(
            SourceItem.id == item_id,
            SourceItem.owner_id == user.id,
            SourceItem.deleted_at.is_(None),
            SourceConnection.status != "deleting",
        )
    )
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "item_not_found", "message": "The selected source item was not found."},
        )
    store: ObjectStore = request.app.state.object_store
    try:
        content = store.get(item.object_key)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=410,
            detail={"code": "source_content_unavailable", "message": "The original source is no longer available."},
        ) from error
    media_type = str(item.metadata_json.get("content_type", "application/octet-stream"))
    is_photo = item.kind == "photo" and media_type.startswith("image/")
    filename = str(item.source_locator.get("filename", "photo")) if is_photo else "source.bin"
    return StreamingResponse(
        BytesIO(content),
        media_type=media_type if is_photo else "application/octet-stream",
        headers={
            "Content-Disposition": ("inline" if is_photo else "attachment") + '; filename="' + filename + '"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/items/{item_id}", status_code=204)
def delete_item_and_source_file(
    item_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    item = session.scalar(
        select(SourceItem).where(
            SourceItem.id == item_id,
            SourceItem.owner_id == user.id,
            SourceItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "item_not_found", "message": "The selected source item was not found."},
        )
    # Every parsed entry points to the same selected source file. Removing a single
    # row while retaining that file would leave deleted text accessible as raw data.
    return delete_source(item.source_id, request, user, session)
