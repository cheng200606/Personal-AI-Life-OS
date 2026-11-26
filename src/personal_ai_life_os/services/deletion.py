"""Durable erasure requests and replay after database backup restoration."""

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_life_os.models import (
    BackgroundJob,
    DesktopDraft,
    DesktopFolderFile,
    GraphEvidence,
    MemoryRecord,
    Reminder,
    Review,
    SourceConnection,
    SourceItem,
    SyncRun,
    User,
)
from personal_ai_life_os.services.graph_evidence import mark_item_evidence_unavailable
from personal_ai_life_os.services.jobs import cancel_all_jobs_for_owner
from personal_ai_life_os.storage import ObjectStore

logger = logging.getLogger(__name__)


def _read_tombstone(store: ObjectStore, *, source_id: str | None = None, owner_id: str | None = None) -> dict | None:
    for _, payload in store.list_deletion_tombstones():
        try:
            document = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if source_id and document.get("source_id") == source_id:
            return document
        if owner_id and not document.get("source_id") and not document.get("item_ids") and document.get("owner_id") == owner_id:
            return document
    return None


def request_item_deletions(
    store: ObjectStore,
    owner_id: str,
    item_ids: set[str],
    *,
    tombstone_id: str | None = None,
    desktop_file_id: str | None = None,
    object_keys: set[str] | None = None,
) -> dict:
    if not item_ids:
        raise ValueError("At least one item ID is required.")
    normalized_ids = sorted({str(UUID(item_id)) for item_id in item_ids})
    key_id = str(UUID(tombstone_id or normalized_ids[0]))
    document = {
        "owner_id": owner_id,
        "tombstone_id": key_id,
        "item_ids": normalized_ids,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    if desktop_file_id:
        document["desktop_file_id"] = str(UUID(desktop_file_id))
        document["object_keys"] = sorted(object_keys or set())
    store.write_item_deletion_tombstone(owner_id, key_id, json.dumps(document).encode("utf-8"))
    return document


def complete_item_deletion(store: ObjectStore, owner_id: str, document: dict) -> None:
    completed = {**document, "completed_at": datetime.now(UTC).isoformat()}
    store.write_item_deletion_tombstone(
        owner_id,
        document["tombstone_id"],
        json.dumps(completed).encode("utf-8"),
    )


def pending_item_deletion(store: ObjectStore, tombstone_id: str) -> dict | None:
    for _, payload in store.list_deletion_tombstones():
        try:
            document = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if document.get("tombstone_id") == tombstone_id and document.get("item_ids"):
            return document
    return None


def erase_desktop_file_records(session: Session, owner_id: str, items: list[SourceItem]) -> None:
    ids = {item.id for item in items}
    if not ids:
        return
    scrub_item_derivatives(session, owner_id, ids, commit=False)
    for item in items:
        item.is_current = False
        item.deleted_at = item.deleted_at or datetime.now(UTC)
        item.title = ""
        item.content_text = ""
        item.object_key = ""
        item.source_locator = {}
        item.metadata_json = {}
    session.execute(update(DesktopDraft).where(DesktopDraft.item_id.in_(ids)).values(
        body="", quote="", status="invalidated",
    ))
    session.execute(update(GraphEvidence).where(GraphEvidence.source_item_id.in_(ids)).values(
        quote="", availability="deleted",
    ))


def remove_desktop_file_objects(session: Session, store: ObjectStore, document: dict) -> None:
    for key in document.get("object_keys", []):
        if not isinstance(key, str) or not key.startswith(f"owners/{document['owner_id']}/"):
            raise ValueError("Invalid desktop deletion journal object key.")
        shared = session.scalar(select(SourceItem.id).where(
            SourceItem.object_key == key, SourceItem.deleted_at.is_(None),
        ).limit(1))
        if not shared:
            store.delete(key)
            session.execute(update(SyncRun).where(SyncRun.object_key == key).values(object_key=None))


def request_source_deletion(store: ObjectStore, owner_id: str, source_id: str) -> dict:
    existing = _read_tombstone(store, source_id=source_id)
    document = existing or {
        "owner_id": owner_id,
        "source_id": source_id,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    store.write_source_deletion_tombstone(owner_id, source_id, json.dumps(document).encode("utf-8"))
    return document


def complete_source_deletion(store: ObjectStore, owner_id: str, source_id: str, document: dict) -> None:
    completed = {**document, "completed_at": datetime.now(UTC).isoformat()}
    store.write_source_deletion_tombstone(owner_id, source_id, json.dumps(completed).encode("utf-8"))


def complete_account_deletion(store: ObjectStore, owner_id: str, document: dict) -> None:
    completed = {**document, "completed_at": datetime.now(UTC).isoformat()}
    store.write_deletion_tombstone(owner_id, json.dumps(completed).encode("utf-8"))


def scrub_item_derivatives(
    session: Session,
    owner_id: str,
    item_ids: set[str],
    *,
    commit: bool = True,
) -> list[SourceItem]:
    items = list(
        session.scalars(
            select(SourceItem).where(
                SourceItem.id.in_(item_ids),
                SourceItem.owner_id == owner_id,
            )
        )
    )
    if not items:
        return []

    reviews = list(
        session.scalars(
            select(Review)
            .join(Review.source_items)
            .where(Review.owner_id == owner_id, SourceItem.id.in_(item_ids))
        ).unique()
    )
    for review in reviews:
        review.status = "invalidated"
        review.final_text = None
        review.draft_json = {"notice": "A source used by this review was deleted. Regenerate the review to restore it."}
        review.source_items = [item for item in review.source_items if item.id not in item_ids]
    if reviews:
        session.execute(
            BackgroundJob.__table__.update()
            .where(
                BackgroundJob.review_id.in_([review.id for review in reviews]),
                BackgroundJob.status.in_(("queued", "running")),
            )
            .values(
                status="cancelled",
                error_code="source_deleting",
                completed_at=datetime.now(UTC),
                lease_expires_at=None,
                worker_id=None,
            )
        )

    records = list(
        session.scalars(
            select(MemoryRecord)
            .join(MemoryRecord.source_items)
            .where(MemoryRecord.owner_id == owner_id, SourceItem.id.in_(item_ids))
        ).unique()
    )
    for record in records:
        record.body = ""
        record.review_status = "invalidated"
        record.source_items = [item for item in record.source_items if item.id not in item_ids]

    reminders = list(
        session.scalars(
            select(Reminder)
            .join(Reminder.source_items)
            .where(Reminder.owner_id == owner_id, SourceItem.id.in_(item_ids))
        ).unique()
    )
    for reminder in reminders:
        reminder.title = "Evidence removed — review this reminder"
        reminder.notes = None
        reminder.status = "cancelled"
        reminder.source_items = [item for item in reminder.source_items if item.id not in item_ids]
    if commit:
        session.commit()
    return items


def scrub_source_derivatives(session: Session, owner_id: str, source_id: str) -> list[SourceItem]:
    item_ids = set(
        session.scalars(
            select(SourceItem.id).where(
                SourceItem.source_id == source_id,
                SourceItem.owner_id == owner_id,
            )
        )
    )
    return scrub_item_derivatives(session, owner_id, item_ids)


def replay_deletion_tombstones(session_factory: sessionmaker, store: ObjectStore) -> int:
    tombstones = store.list_deletion_tombstones()
    replayed = 0
    for key, payload in tombstones:
        try:
            document = json.loads(payload)
            owner_id = str(UUID(document["owner_id"]))
            source_id = str(UUID(document["source_id"])) if document.get("source_id") else None
            raw_item_ids = document.get("item_ids")
            desktop_file_id = str(UUID(document["desktop_file_id"])) if "desktop_file_id" in document else None
            is_item_document = "item_ids" in document or "tombstone_id" in document
            if is_item_document:
                if source_id or not isinstance(raw_item_ids, list) or not raw_item_ids:
                    raise ValueError("An item deletion tombstone must contain only a non-empty item_ids list.")
                UUID(document["tombstone_id"])
                item_ids = {str(UUID(item_id)) for item_id in raw_item_ids}
            else:
                item_ids = set()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("A data deletion tombstone is malformed; startup is blocked.") from error

        with session_factory() as session:
            user = session.scalar(select(User).where(User.id == owner_id))
            if item_ids:
                if user is not None:
                    items = list(
                        session.scalars(
                            select(SourceItem).where(
                                SourceItem.owner_id == owner_id,
                                SourceItem.id.in_(item_ids),
                            )
                        )
                    )
                    for item in items:
                        item.is_current = False
                        item.deleted_at = item.deleted_at or datetime.now(UTC)
                    if desktop_file_id:
                        erase_desktop_file_records(session, owner_id, items)
                        entry = session.get(DesktopFolderFile, desktop_file_id)
                        if entry:
                            source = session.get(SourceConnection, entry.source_id)
                            if source and source.owner_id == owner_id:
                                entry.status = "deleted"
                        session.flush()
                        remove_desktop_file_objects(session, store, document)
                    else:
                        scrub_item_derivatives(session, owner_id, item_ids, commit=False)
                        mark_item_evidence_unavailable(
                            session, owner_id=owner_id, item_ids=item_ids, availability="deleted",
                        )
                    session.commit()
                if not document.get("completed_at"):
                    complete_item_deletion(store, owner_id, document)
            elif source_id:
                if user is not None:
                    source = session.scalar(
                        select(SourceConnection).where(
                            SourceConnection.id == source_id,
                            SourceConnection.owner_id == owner_id,
                        )
                    )
                    if source is not None:
                        source.status = "deleting"
                        session.commit()
                        items = scrub_source_derivatives(session, owner_id, source_id)
                        keys = {item.object_key for item in items if item.object_key}
                        keys.update(
                            key
                            for key in session.scalars(
                                select(SyncRun.object_key).where(
                                    SyncRun.owner_id == owner_id,
                                    SyncRun.source_id == source_id,
                                    SyncRun.object_key.is_not(None),
                                )
                            )
                            if key
                        )
                        for object_key in keys:
                            store.delete(object_key)
                        store.delete_source_objects(owner_id, source_id)
                        session.delete(source)
                        session.commit()
                store.delete_source_objects(owner_id, source_id)
                if not document.get("completed_at"):
                    complete_source_deletion(store, owner_id, source_id, document)
            else:
                if user is not None:
                    user.deletion_requested_at = user.deletion_requested_at or datetime.now(UTC)
                    cancel_all_jobs_for_owner(session, owner_id)
                    sources = list(
                        session.scalars(select(SourceConnection).where(SourceConnection.owner_id == owner_id))
                    )
                    for source in sources:
                        source.status = "deleting"
                    session.commit()

                    keys = set(
                        session.scalars(select(SourceItem.object_key).where(SourceItem.owner_id == owner_id))
                    )
                    keys.update(
                        object_key
                        for object_key in session.scalars(
                            select(SyncRun.object_key).where(
                                SyncRun.owner_id == owner_id,
                                SyncRun.object_key.is_not(None),
                            )
                        )
                        if object_key
                    )
                    for object_key in keys:
                        store.delete(object_key)
                    store.delete_owner_objects(owner_id)
                    session.delete(user)
                    session.commit()
                else:
                    store.delete_owner_objects(owner_id)
                if not document.get("completed_at"):
                    complete_account_deletion(store, owner_id, document)
        replayed += 1
    if replayed:
        logger.info("Replayed %d data deletion tombstone(s).", replayed)
    return replayed
