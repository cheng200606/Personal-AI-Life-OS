"""Configure desktop analysis and review evidence-backed suggestions."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, select, update

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.models import (
    BackgroundJob,
    DesktopDraft,
    MemoryRecord,
    Reminder,
    SourceConnection,
    SourceItem,
)
from personal_ai_life_os.services.desktop_provider import PROVIDER_ID, DesktopProviderSettings
from personal_ai_life_os.services.jobs import cancel_model_jobs_for_owner

router = APIRouter(prefix="/desktop/analysis", tags=["desktop"])


class DraftEdit(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class DraftDecision(BaseModel):
    ids: set[str] = Field(min_length=1, max_length=100)
    decision: Literal["accepted", "rejected"]


@router.get("/provider")
def get_provider(request: Request, user: CurrentUserDep) -> dict:
    return request.app.state.desktop_provider.public()


@router.put("/provider")
def configure_provider(
    payload: DesktopProviderSettings, request: Request, user: CurrentUserDep, session: SessionDep,
) -> dict:
    try:
        result = request.app.state.desktop_provider.save(payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except OSError:
        raise HTTPException(503, "Windows could not save the provider settings or credential.") from None
    cancel_model_jobs_for_owner(session, user.id, provider_id=PROVIDER_ID)
    session.commit()
    return result


@router.delete("/provider", status_code=204)
def remove_provider(request: Request, user: CurrentUserDep, session: SessionDep) -> None:
    request.app.state.desktop_provider.clear()
    cancel_model_jobs_for_owner(session, user.id, provider_id=PROVIDER_ID)
    session.commit()


def _draft_rows(owner_id: str):
    return (
        select(DesktopDraft, SourceItem, SourceConnection)
        .join(SourceItem, SourceItem.id == DesktopDraft.item_id)
        .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
        .where(
            DesktopDraft.owner_id == owner_id, DesktopDraft.status == "pending",
            SourceItem.is_current.is_(True), SourceItem.deleted_at.is_(None),
            SourceConnection.status.in_(("active", "paused")),
        )
    )


@router.get("/drafts")
def list_drafts(
    user: CurrentUserDep, session: SessionDep,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
) -> list[dict]:
    priority = case((DesktopDraft.kind == "experience", 1), (DesktopDraft.kind == "knowledge", 2), else_=3)
    return [
        {
            "id": draft.id, "kind": draft.kind, "body": draft.body, "quote": draft.quote,
            "confidence": draft.confidence, "item_id": item.id, "item_title": item.title,
            "locator": item.source_locator, "source_id": source.id, "source_name": source.name,
        }
        for draft, item, source in session.execute(
            _draft_rows(user.id).order_by(SourceConnection.name, priority, DesktopDraft.created_at.desc(), DesktopDraft.id)
            .offset(offset).limit(limit),
        )
    ]


@router.patch("/drafts/{draft_id}", status_code=204)
def update_draft(draft_id: str, payload: DraftEdit, user: CurrentUserDep, session: SessionDep) -> None:
    row = session.execute(_draft_rows(user.id).where(DesktopDraft.id == draft_id)).one_or_none()
    if row is None or not payload.body.strip():
        raise HTTPException(409, "This draft is unavailable or empty.")
    changed = session.execute(update(DesktopDraft).where(
        DesktopDraft.id == draft_id, DesktopDraft.status == "pending",
    ).values(body=payload.body.strip()))
    if changed.rowcount != 1:
        raise HTTPException(409, "This draft has already been reviewed.")
    session.commit()


@router.post("/drafts/decision")
def decide_drafts(payload: DraftDecision, user: CurrentUserDep, session: SessionDep) -> dict:
    rows = list(session.execute(_draft_rows(user.id).where(DesktopDraft.id.in_(payload.ids))))
    if len(rows) != len(payload.ids):
        raise HTTPException(409, "Some selected drafts changed. Refresh the inbox and preview again.")
    for draft, item, _ in rows:
        changed = session.execute(update(DesktopDraft).where(
            DesktopDraft.id == draft.id, DesktopDraft.status == "pending",
        ).values(status=payload.decision))
        if changed.rowcount != 1:
            raise HTTPException(409, "Some selected drafts were already reviewed.")
        if payload.decision == "rejected":
            continue
        if draft.kind == "action":
            session.add(Reminder(
                owner_id=user.id, title=draft.body[:500], notes=draft.body if len(draft.body) > 500 else None,
                status="pending", source_items=[item],
            ))
        else:
            session.add(MemoryRecord(
                owner_id=user.id, kind=draft.kind, body=draft.body, generated_by="desktop_ai",
                review_status="confirmed", occurred_at=item.occurred_at, source_items=[item],
            ))
    session.commit()
    return {"reviewed": len(rows)}


@router.get("/confirmed")
def confirmed_notes(user: CurrentUserDep, session: SessionDep) -> list[dict]:
    return [
        {"id": note.id, "kind": note.kind, "body": note.body, "item_id": item.id,
         "item_title": item.title, "source_id": source.id, "source_name": source.name}
        for note, item, source in session.execute(
            select(MemoryRecord, SourceItem, SourceConnection)
            .join(MemoryRecord.source_items).join(SourceConnection, SourceConnection.id == SourceItem.source_id)
            .where(
                MemoryRecord.owner_id == user.id, MemoryRecord.generated_by == "desktop_ai",
                MemoryRecord.review_status == "confirmed", SourceItem.deleted_at.is_(None),
                SourceItem.is_current.is_(True), SourceConnection.status.in_(("active", "paused")),
            ).order_by(MemoryRecord.created_at.desc()).limit(100)
        )
    ]


@router.get("/jobs")
def list_analysis_jobs(user: CurrentUserDep, session: SessionDep) -> list[dict]:
    return [
        {"id": job.id, "source_name": source.name, "status": job.status, "error_code": job.error_code,
         "attempt_count": job.attempt_count, "item_id": job.source_item_id, "result": job.result_json}
        for job, source in session.execute(
            select(BackgroundJob, SourceConnection).join(SourceConnection).where(
                BackgroundJob.owner_id == user.id, BackgroundJob.kind == "desktop_analysis",
            ).order_by(BackgroundJob.created_at.desc()).limit(100),
        )
    ]
