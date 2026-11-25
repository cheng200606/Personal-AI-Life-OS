"""Portable data archive and retryable account deletion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, DeletionUserDep, SessionDep
from personal_ai_life_os.models import (
    BackgroundJob,
    ModelRun,
    Reminder,
    Review,
    SourceConnection,
    SourceItem,
    SyncRun,
)
from personal_ai_life_os.services.jobs import cancel_all_jobs_for_owner
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(prefix="/account", tags=["account"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


@router.get("/archive")
def download_archive(
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    sources = list(session.scalars(select(SourceConnection).where(SourceConnection.owner_id == user.id)))
    runs = list(session.scalars(select(SyncRun).where(SyncRun.owner_id == user.id)))
    items = list(
        session.scalars(
            select(SourceItem).where(
                SourceItem.owner_id == user.id,
                SourceItem.deleted_at.is_(None),
            )
        )
    )
    reviews = list(session.scalars(select(Review).where(Review.owner_id == user.id)))
    reminders = list(session.scalars(select(Reminder).where(Reminder.owner_id == user.id)))
    model_runs = list(session.scalars(select(ModelRun).where(ModelRun.owner_id == user.id)))
    jobs = list(
        session.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.owner_id == user.id)
            .order_by(BackgroundJob.created_at, BackgroundJob.id)
        )
    )
    archive = BytesIO()
    missing_objects: list[str] = []
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.writestr(
            "account.json",
            _json_bytes({"email": user.email, "timezone": user.timezone, "created_at": _iso(user.created_at)}),
        )
        bundle.writestr(
            "sources.json",
            _json_bytes(
                [
                    {
                        "id": source.id,
                        "kind": source.kind,
                        "name": source.name,
                        "status": source.status,
                        "consent_version": source.consent_version,
                        "selected_scope": source.selected_scope,
                        "created_at": _iso(source.created_at),
                        "last_sync_at": _iso(source.last_sync_at),
                    }
                    for source in sources
                ]
            ),
        )
        bundle.writestr(
            "sync-runs.json",
            _json_bytes(
                [
                    {
                        "id": run.id,
                        "source_id": run.source_id,
                        "status": run.status,
                        "parser_version": run.parser_version,
                        "file_sha256": run.file_sha256,
                        "items_seen": run.items_seen,
                        "items_created": run.items_created,
                        "items_duplicate": run.items_duplicate,
                        "items_failed": run.items_failed,
                        "error_code": run.error_code,
                        "created_at": _iso(run.created_at),
                        "completed_at": _iso(run.completed_at),
                    }
                    for run in runs
                ]
            ),
        )
        bundle.writestr(
            "timeline.json",
            _json_bytes(
                [
                    {
                        "id": item.id,
                        "source_id": item.source_id,
                        "kind": item.kind,
                        "title": item.title,
                        "content_text": item.content_text,
                        "occurred_at": _iso(item.occurred_at),
                        "source_timezone": item.source_timezone,
                        "source_sha256": item.source_sha256,
                        "parser_version": item.parser_version,
                        "source_locator": item.source_locator,
                        "metadata": item.metadata_json,
                    }
                    for item in items
                ]
            ),
        )
        bundle.writestr(
            "reviews.json",
            _json_bytes(
                [
                    {
                        "id": review.id,
                        "period_start": _iso(review.period_start),
                        "period_end": _iso(review.period_end),
                        "status": review.status,
                        "draft": review.draft_json,
                        "final_text": review.final_text,
                        "source_ids": [item.id for item in review.source_items if item.deleted_at is None],
                    }
                    for review in reviews
                ]
            ),
        )
        bundle.writestr(
            "reminders.json",
            _json_bytes(
                [
                    {
                        "id": reminder.id,
                        "title": reminder.title,
                        "notes": reminder.notes,
                        "due_at": _iso(reminder.due_at),
                        "status": reminder.status,
                        "source_ids": [item.id for item in reminder.source_items if item.deleted_at is None],
                    }
                    for reminder in reminders
                ]
            ),
        )
        bundle.writestr(
            "model-usage.json",
            _json_bytes(
                [
                    {
                        "provider": run.provider,
                        "model": run.model,
                        "purpose": run.purpose,
                        "status": run.status,
                        "prompt_version": run.prompt_version,
                        "latency_ms": run.latency_ms,
                        "input_tokens": run.input_tokens,
                        "output_tokens": run.output_tokens,
                        "cost_usd": str(run.cost_usd) if run.cost_usd is not None else None,
                        "created_at": _iso(run.created_at),
                    }
                    for run in model_runs
                ]
            ),
        )
        bundle.writestr(
            "background-jobs.json",
            _json_bytes(
                [
                    {
                        "id": job.id,
                        "kind": job.kind,
                        "status": job.status,
                        "error_code": job.error_code,
                        "result": job.result_json,
                        "created_at": _iso(job.created_at),
                        "completed_at": _iso(job.completed_at),
                    }
                    for job in jobs
                ]
            ),
        )
        store: ObjectStore = request.app.state.object_store
        object_keys = {run.object_key for run in runs if run.object_key}
        object_keys.update(item.object_key for item in items if item.object_key)
        for key in sorted(object_keys):
            try:
                content = store.get(key)
            except FileNotFoundError:
                missing_objects.append(key.rsplit("/", 1)[-1])
                continue
            source_id = key.split("/")[3] if len(key.split("/")) > 3 else "source"
            digest = key.split("/")[-2] if len(key.split("/")) > 1 else "object"
            bundle.writestr("originals/" + source_id + "/" + digest + ".bin", content)
        bundle.writestr("archive-manifest.json", _json_bytes({"missing_object_files": missing_objects}))
        bundle.writestr(
            "README.txt",
            "Personal AI Life OS account export. JSON files use UTF-8. The originals directory contains selected, stored source files; ChatGPT exports are minimized to chosen conversations and photos are sanitized copies. Keep this archive private.",
        )
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="lifeos-archive.zip"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("", status_code=204)
def delete_account(request: Request, user: DeletionUserDep, session: SessionDep) -> Response:
    if user.deletion_requested_at is None:
        store: ObjectStore = request.app.state.object_store
        tombstone = _json_bytes({"owner_id": user.id, "requested_at": datetime.now(UTC).isoformat()})
        try:
            store.write_deletion_tombstone(user.id, tombstone)
        except Exception as error:
            raise HTTPException(
                503,
                detail={"code": "account_tombstone_pending", "message": "Deletion could not be durably recorded. Retry shortly."},
            ) from error
        user.deletion_requested_at = datetime.now(UTC)
        cancel_all_jobs_for_owner(session, user.id)
        for source in session.scalars(
            select(SourceConnection).where(SourceConnection.owner_id == user.id)
        ):
            source.status = "deleting"
        session.commit()

    keys = set(
        session.scalars(
            select(SourceItem.object_key).where(SourceItem.owner_id == user.id)
        )
    )
    keys.update(
        key
        for key in session.scalars(
            select(SyncRun.object_key).where(
                SyncRun.owner_id == user.id,
                SyncRun.object_key.is_not(None),
            )
        )
        if key
    )
    store: ObjectStore = request.app.state.object_store
    try:
        for key in keys:
            store.delete(key)
        store.delete_owner_objects(user.id)
        store.write_deletion_tombstone(
            user.id,
            _json_bytes(
                {
                    "owner_id": user.id,
                    "requested_at": user.deletion_requested_at.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
    except Exception as error:
        raise HTTPException(
            503,
            detail={"code": "account_cleanup_pending", "message": "Account access is disabled. Retry deletion to finish object cleanup."},
        ) from error

    session.delete(user)
    session.commit()
    return Response(status_code=204)
