"""Bounded file upload and text source imports."""

import json
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import or_, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    ImportResultResponse,
    SourceItemResponse,
    SyncRunResponse,
)
from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import BackgroundJob, SourceConnection
from personal_ai_life_os.services.ingestion import IngestionFailure, ingest_file, response_item
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(tags=["imports"])


@router.post("/sources/{source_id}/imports", response_model=ImportResultResponse, status_code=201)
def import_file(
    source_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    conversation_ids: Annotated[str | None, Form()] = None,
    captured_at: Annotated[str | None, Form()] = None,
    captured_timezone: Annotated[str | None, Form()] = None,
) -> dict:
    source = session.scalar(
        select(SourceConnection).where(
            SourceConnection.id == source_id,
            SourceConnection.owner_id == user.id,
        )
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "source_not_found", "message": "The selected source was not found."},
        )
    config: Settings = request.app.state.settings
    limit = (
        config.max_photo_upload_bytes
        if source.kind == "photo"
        else config.max_text_upload_bytes
    )
    payload = file.file.read(limit + 1)
    if len(payload) > limit:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "upload_too_large",
                "message": f"This upload exceeds the configured {limit} byte limit.",
            },
        )
    selected_ids: set[str] | None = None
    captured_datetime: datetime | None = None
    if captured_at:
        try:
            captured_datetime = datetime.fromisoformat(captured_at)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_capture_date", "message": "captured_at must be an ISO 8601 timestamp."},
            ) from error
        if captured_datetime.tzinfo is None or captured_datetime.utcoffset() is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_capture_date", "message": "captured_at must include a timezone offset."},
            )
    if captured_timezone:
        try:
            ZoneInfo(captured_timezone)
        except ZoneInfoNotFoundError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_capture_timezone", "message": "Use a valid IANA timezone name."},
            ) from error
    if conversation_ids:
        try:
            decoded = json.loads(conversation_ids)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_conversation_selection", "message": "conversation_ids must be a JSON array."},
            ) from error
        if not isinstance(decoded, list) or not all(isinstance(value, str) for value in decoded):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_conversation_selection", "message": "conversation_ids must be a JSON array of strings."},
            )
        selected_ids = {value for value in decoded if value}

    store: ObjectStore = request.app.state.object_store
    try:
        run, items = ingest_file(
            session=session,
            store=store,
            source=source,
            owner_id=user.id,
            filename=file.filename or "source",
            content_type=file.content_type or "application/octet-stream",
            payload=payload,
            conversation_ids=selected_ids,
            captured_at=captured_datetime,
            source_timezone=captured_timezone,
            user_timezone=user.timezone,
            defer_photo_ocr=(source.kind == "photo" and config.processing_mode == "worker"),
            desktop_config=config if config.app_env == "desktop" else None,
        )
    except IngestionFailure as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    job_ids = list(
        session.scalars(
            select(BackgroundJob.id).where(or_(
                BackgroundJob.sync_run_id == run.id,
                BackgroundJob.source_item_id.in_([item.id for item in items if item.sync_run_id == run.id]),
            ))
        )
    )
    return {
        "sync_run": SyncRunResponse.model_validate(run),
        "items": [SourceItemResponse.model_validate(response_item(item)) for item in items],
        "job_ids": job_ids,
    }
