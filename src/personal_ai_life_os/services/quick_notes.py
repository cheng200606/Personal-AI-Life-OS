"""User-authored quick notes backed by owner-scoped source items."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.api.schemas import QuickNoteCreateRequest, QuickNoteUpdateRequest
from personal_ai_life_os.models import SourceConnection, SourceItem, SyncRun, new_id
from personal_ai_life_os.services.deletion import (
    complete_item_deletion,
    pending_item_deletion,
    request_item_deletions,
    scrub_item_derivatives,
)
from personal_ai_life_os.services.graph_evidence import mark_item_evidence_unavailable
from personal_ai_life_os.services.ingestion import response_item
from personal_ai_life_os.storage import ObjectStore

PARSER_VERSION = "quick-note-v1"


class QuickNoteNotFound(LookupError):
    pass


def _title(content: str, requested: str | None) -> str:
    if requested:
        return requested
    first_line = next((line.strip().lstrip("#").strip() for line in content.splitlines() if line.strip()), "")
    return first_line[:120] or "Quick note"


def _digest(title: str, content: str, occurred_at: datetime | None, timezone: str | None) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "title": title,
                "content_text": content,
                "occurred_at": occurred_at.isoformat() if occurred_at else None,
                "source_timezone": timezone,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _note_source(session: Session, owner_id: str) -> SourceConnection:
    source = session.scalar(
        select(SourceConnection).where(
            SourceConnection.owner_id == owner_id,
            SourceConnection.kind == "quick_note",
            SourceConnection.status != "deleting",
        ).order_by(SourceConnection.created_at, SourceConnection.id).limit(1)
    )
    if source is None:
        source = SourceConnection(
            owner_id=owner_id,
            kind="quick_note",
            name="Quick notes",
            status="active",
            consent_version="source-consent-v1",
            selected_scope={"internal": True},
        )
        session.add(source)
        session.flush()
    if source.status != "active":
        raise ValueError("Quick notes are unavailable while their internal source is not active.")
    return source


def _note_query(session: Session, owner_id: str, item_id: str):
    return (
        select(SourceItem)
        .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
        .where(
            SourceItem.id == item_id,
            SourceItem.owner_id == owner_id,
            SourceItem.kind == "quick_note",
            SourceItem.deleted_at.is_(None),
            SourceItem.is_current.is_(True),
            SourceConnection.status != "deleting",
        )
    )


def create_quick_note(session: Session, owner_id: str, payload: QuickNoteCreateRequest) -> dict:
    source = _note_source(session, owner_id)
    content = payload.content_text
    title = _title(content, payload.title)
    occurred_at = payload.occurred_at.astimezone(UTC) if payload.occurred_at else None
    timezone = payload.source_timezone if occurred_at else None
    digest = _digest(title, content, occurred_at, timezone)
    now = datetime.now(UTC)
    run = SyncRun(
        owner_id=owner_id,
        source_id=source.id,
        status="completed",
        parser_version=PARSER_VERSION,
        file_sha256=digest,
        items_seen=1,
        items_created=1,
        completed_at=now,
    )
    session.add(run)
    session.flush()
    item = SourceItem(
        owner_id=owner_id,
        source_id=source.id,
        sync_run_id=run.id,
        external_id=new_id(),
        kind="quick_note",
        title=title,
        content_text=content,
        occurred_at=occurred_at,
        source_timezone=timezone,
        source_sha256=digest,
        stored_sha256=digest,
        parser_version=PARSER_VERSION,
        object_key="",
        source_locator={"kind": "quick_note"},
        metadata_json={
            "content_type": "text/markdown",
            "created_by": "user",
            "updated_at": now.isoformat(),
        },
        is_current=True,
    )
    session.add(item)
    source.last_sync_at = now
    session.commit()
    session.refresh(item)
    return response_item(item)


def update_quick_note(
    session: Session,
    owner_id: str,
    item_id: str,
    payload: QuickNoteUpdateRequest,
) -> dict:
    item = session.scalar(_note_query(session, owner_id, item_id))
    if item is None:
        raise QuickNoteNotFound(item_id)
    fields = payload.model_fields_set
    content = payload.content_text if "content_text" in fields else item.content_text
    title = _title(content, payload.title if "title" in fields else item.title)
    if payload.clear_occurred_at:
        occurred_at = None
    elif "occurred_at" in fields:
        occurred_at = payload.occurred_at.astimezone(UTC) if payload.occurred_at else None
    else:
        occurred_at = item.occurred_at
    if payload.clear_source_timezone:
        timezone = None
    elif "source_timezone" in fields:
        timezone = payload.source_timezone
    else:
        timezone = item.source_timezone
    timezone = timezone if occurred_at else None
    digest = _digest(title, content, occurred_at, timezone)
    now = datetime.now(UTC)
    run = SyncRun(
        owner_id=owner_id,
        source_id=item.source_id,
        status="completed",
        parser_version=PARSER_VERSION,
        file_sha256=digest,
        items_seen=1,
        items_updated=1,
        completed_at=now,
    )
    session.add(run)
    session.flush()
    item.sync_run_id = run.id
    item.title = title
    item.content_text = content
    item.occurred_at = occurred_at
    item.source_timezone = timezone
    item.source_sha256 = digest
    item.stored_sha256 = digest
    item.metadata_json = {**item.metadata_json, "updated_at": now.isoformat()}
    item.source.last_sync_at = now
    session.commit()
    session.refresh(item)
    return response_item(item)


def delete_quick_note(
    session: Session,
    store: ObjectStore,
    owner_id: str,
    item_id: str,
) -> None:
    item = session.scalar(_note_query(session, owner_id, item_id))
    if item is None:
        document = pending_item_deletion(store, item_id)
        if document is not None and document.get("owner_id") == owner_id:
            complete_item_deletion(store, owner_id, document)
            return
        raise QuickNoteNotFound(item_id)
    document = request_item_deletions(store, owner_id, {item.id})
    item.is_current = False
    item.deleted_at = datetime.now(UTC)
    item.metadata_json = {**item.metadata_json, "deleted_at": item.deleted_at.isoformat()}
    scrub_item_derivatives(session, owner_id, {item.id}, commit=False)
    mark_item_evidence_unavailable(
        session,
        owner_id=owner_id,
        item_ids={item.id},
        availability="deleted",
    )
    session.commit()
    complete_item_deletion(store, owner_id, document)
