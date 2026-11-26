"""Synchronous, retry-safe ingestion for bounded local file imports."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import Uuid, literal, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import (
    SourceConnection,
    SourceItem,
    SyncRun,
    item_collections,
    item_tags,
    new_id,
)
from personal_ai_life_os.parsers.base import ParsedItem
from personal_ai_life_os.parsers.calendar_ics import (
    PARSER_VERSION as CALENDAR_PARSER_VERSION,
)
from personal_ai_life_os.parsers.calendar_ics import (
    UnsupportedCalendarError,
    parse_calendar,
)
from personal_ai_life_os.parsers.chatgpt_export import (
    PARSER_VERSION as CHATGPT_PARSER_VERSION,
)
from personal_ai_life_os.parsers.chatgpt_export import (
    UnsupportedExportError,
    parse_chatgpt_export,
    select_chatgpt_export,
)
from personal_ai_life_os.parsers.document import (
    PARSER_VERSION as DOCUMENT_PARSER_VERSION,
)
from personal_ai_life_os.parsers.document import (
    UnsupportedDocumentError,
    parse_document,
)
from personal_ai_life_os.parsers.generic_chat import (
    PARSER_VERSION as GENERIC_CHAT_PARSER_VERSION,
)
from personal_ai_life_os.parsers.generic_chat import (
    UnsupportedChatExportError,
    parse_generic_chat,
)
from personal_ai_life_os.parsers.memory_markdown import (
    PARSER_VERSION as MEMORY_PARSER_VERSION,
)
from personal_ai_life_os.parsers.memory_markdown import (
    parse_memory_markdown,
)
from personal_ai_life_os.parsers.photo import (
    PARSER_VERSION as PHOTO_PARSER_VERSION,
)
from personal_ai_life_os.parsers.photo import (
    UnsupportedPhotoError,
    process_photo,
)
from personal_ai_life_os.services.deletion import (
    complete_item_deletion,
    request_item_deletions,
    scrub_item_derivatives,
)
from personal_ai_life_os.services.graph_evidence import mark_item_evidence_unavailable
from personal_ai_life_os.services.jobs import enqueue_background_job
from personal_ai_life_os.storage import ObjectStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionFailure(Exception):
    code: str
    message: str
    status_code: int = 422


def _safe_filename(filename: str) -> str:
    cleaned = filename.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned).strip("._")
    return cleaned[:180] or "source"


def _parser_for(
    source: SourceConnection,
    payload: bytes,
    filename: str,
    upload_content_type: str,
    conversation_ids: set[str] | None,
    captured_at: datetime | None,
    source_timezone: str | None,
    user_timezone: str,
    defer_photo_ocr: bool,
) -> tuple[list[ParsedItem], str, bytes, str]:
    if source.kind in {"memory_markdown", "document"}:
        if source.kind == "memory_markdown" and not filename.lower().endswith((".md", ".markdown")):
            raise IngestionFailure("unsupported_file_type", "Select a Markdown file ending in .md.")
        try:
            if source.kind == "memory_markdown":
                text = payload.decode("utf-8-sig")
                parsed = parse_memory_markdown(text, _safe_filename(filename))
                parser_version = MEMORY_PARSER_VERSION
            else:
                parsed = parse_document(payload, _safe_filename(filename))
                parser_version = DOCUMENT_PARSER_VERSION
        except UnicodeDecodeError as error:
            raise IngestionFailure("invalid_encoding", "The Markdown file must be UTF-8 encoded.") from error
        except UnsupportedDocumentError as error:
            raise IngestionFailure("unsupported_document", str(error)) from error
        zone = ZoneInfo(user_timezone)
        normalized = []
        for item in parsed:
            if item.metadata.get("date_precision") == "day" and item.occurred_at is not None:
                local_day = item.occurred_at.date()
                normalized.append(
                    replace(
                        item,
                        occurred_at=datetime.combine(local_day, time.min, tzinfo=zone).astimezone(UTC),
                        metadata={**item.metadata, "date_basis_timezone": user_timezone},
                    )
                )
            else:
                normalized.append(item)
        return normalized, parser_version, payload, upload_content_type
    if source.kind == "chat_export":
        if not filename.lower().endswith((".json", ".jsonl")):
            raise IngestionFailure("unsupported_file_type", "Select a JSON or JSONL chat export.")
        try:
            items = parse_generic_chat(payload, _safe_filename(filename))
        except UnsupportedChatExportError as error:
            raise IngestionFailure("unsupported_export", str(error)) from error
        return items, GENERIC_CHAT_PARSER_VERSION, payload, upload_content_type or "application/json"
    if source.kind == "chatgpt_export":
        if not filename.lower().endswith(".json"):
            raise IngestionFailure("unsupported_file_type", "Select the ChatGPT conversations JSON export.")
        authorized = set(source.selected_scope.get("conversation_ids", []))
        selected = authorized if conversation_ids is None else conversation_ids
        if not selected:
            raise IngestionFailure(
                "conversation_selection_required",
                "Choose one or more conversations in the local preview before uploading.",
            )
        if not selected.issubset(authorized):
            raise IngestionFailure(
                "conversation_scope_exceeded",
                "The upload contains a conversation that was not included in the saved source selection.",
                403,
            )
        try:
            minimized_payload = select_chatgpt_export(payload, selected)
            items = parse_chatgpt_export(minimized_payload, selected)
        except UnsupportedExportError as error:
            raise IngestionFailure("unsupported_export", str(error)) from error
        return items, CHATGPT_PARSER_VERSION, minimized_payload, "application/json"
    if source.kind == "calendar_ics":
        if not filename.lower().endswith(".ics"):
            raise IngestionFailure("unsupported_file_type", "Select an iCalendar file ending in .ics.")
        try:
            preview = parse_calendar(payload, user_timezone=user_timezone)
        except UnsupportedCalendarError as error:
            raise IngestionFailure("unsupported_calendar", str(error)) from error
        return list(preview.items), CALENDAR_PARSER_VERSION, payload, "text/calendar"
    if source.kind == "photo":
        try:
            processed = process_photo(
                payload,
                _safe_filename(filename),
                captured_at=captured_at,
                source_timezone=source_timezone,
                defer_ocr=defer_photo_ocr,
            )
        except UnsupportedPhotoError as error:
            raise IngestionFailure("unsupported_photo", str(error)) from error
        return [processed.item], PHOTO_PARSER_VERSION, processed.sanitized_bytes, processed.content_type
    raise IngestionFailure("unsupported_source_type", "This source type does not accept text imports.", 409)


def _insert_source_item(session: Session, values: dict) -> bool:
    dialect_name = session.get_bind().dialect.name
    identity = ["owner_id", "source_id", "external_id", "source_sha256"]
    if dialect_name == "postgresql":
        statement = postgresql_insert(SourceItem).values(**values).on_conflict_do_nothing(
            index_elements=identity
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(SourceItem).values(**values).on_conflict_do_nothing(
            index_elements=identity
        )
    else:
        raise RuntimeError(f"Unsupported database dialect for idempotent ingestion: {dialect_name}")
    result = session.execute(statement)
    return result.rowcount == 1


def _record_hash(parsed: ParsedItem) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "external_id": parsed.external_id,
                "kind": parsed.kind,
                "title": parsed.title,
                "content_text": parsed.content_text,
                "occurred_at": parsed.occurred_at.isoformat() if parsed.occurred_at else None,
                "source_locator": parsed.source_locator,
                "metadata": parsed.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _copy_item_organization(session: Session, old_item_id: str, new_item_id: str) -> None:
    for table, column_name in ((item_tags, "tag_id"), (item_collections, "collection_id")):
        session.execute(
            table.insert().from_select(
                ["item_id", column_name],
                select(literal(new_item_id, type_=Uuid(as_uuid=False)), table.c[column_name]).where(table.c.item_id == old_item_id),
            )
        )


def _persist_calendar_items(
    *,
    session: Session,
    source: SourceConnection,
    owner_id: str,
    run: SyncRun,
    parsed_items: list[ParsedItem],
    stored_hash: str,
    object_key: str,
    parser_version: str,
    store: ObjectStore,
) -> tuple[list[SourceItem], dict | None]:
    current_items = list(
        session.scalars(
            select(SourceItem).where(
                SourceItem.owner_id == owner_id,
                SourceItem.source_id == source.id,
                SourceItem.is_current.is_(True),
                SourceItem.deleted_at.is_(None),
            )
        )
    )
    by_external_id = {item.external_id: item for item in current_items}
    snapshot_ids = {item.external_id for item in parsed_items}
    cancelled_ids = {
        by_external_id[item.external_id].id
        for item in parsed_items
        if item.metadata.get("ics_status") == "cancelled"
        and not item.metadata.get("ics_unsupported_recurrence")
        and item.external_id in by_external_id
        and int(item.metadata.get("ics_sequence", 0))
        >= int((by_external_id[item.external_id].metadata_json or {}).get("ics_sequence", -1))
    }
    missing_ids = {
        item.id for external_id, item in by_external_id.items() if external_id not in snapshot_ids
    }
    deletion_document = None
    removal_candidates = cancelled_ids | missing_ids
    if removal_candidates:
        deletion_document = request_item_deletions(
            store,
            owner_id,
            removal_candidates,
            tombstone_id=run.id,
        )
    removed_ids: set[str] = set()
    persisted: list[SourceItem] = []

    for parsed in parsed_items:
        if parsed.metadata.get("ics_unsupported_recurrence"):
            run.items_skipped += 1
            continue
        existing = by_external_id.get(parsed.external_id)
        sequence = int(parsed.metadata.get("ics_sequence", 0))
        existing_sequence = int((existing.metadata_json or {}).get("ics_sequence", -1)) if existing else -1
        if existing is not None and sequence < existing_sequence:
            run.items_skipped += 1
            continue
        if parsed.metadata.get("ics_status") == "cancelled":
            if existing is not None:
                existing.is_current = False
                existing.deleted_at = datetime.now(UTC)
                removed_ids.add(existing.id)
                run.items_removed += 1
            else:
                run.items_skipped += 1
            continue

        record_hash = _record_hash(parsed)
        existing_digest = (existing.metadata_json or {}).get("content_digest") if existing else None
        if existing is not None and existing_digest == record_hash:
            run.items_duplicate += 1
            persisted.append(existing)
            continue

        metadata = {
            **parsed.metadata,
            "content_digest": record_hash,
            "snapshot_id": run.file_sha256,
            "content_type": "text/calendar",
        }
        values = {
            "id": new_id(),
            "owner_id": owner_id,
            "source_id": source.id,
            "sync_run_id": run.id,
            "external_id": parsed.external_id,
            "kind": parsed.kind,
            "title": parsed.title[:500],
            "content_text": parsed.content_text,
            "occurred_at": parsed.occurred_at,
            "source_timezone": parsed.source_timezone,
            "source_sha256": hashlib.sha256(f"{record_hash}:{run.id}".encode("ascii")).hexdigest(),
            "stored_sha256": stored_hash,
            "parser_version": parser_version,
            "object_key": object_key,
            "source_locator": parsed.source_locator,
            "metadata_json": metadata,
            "is_current": True,
        }
        if existing is not None:
            existing.is_current = False
        if _insert_source_item(session, values):
            item = session.get(SourceItem, values["id"])
            if item is not None:
                if existing is not None:
                    _copy_item_organization(session, existing.id, item.id)
                persisted.append(item)
            if existing is not None:
                run.items_updated += 1
            else:
                run.items_created += 1
        else:
            run.items_skipped += 1

    for external_id, existing in by_external_id.items():
        if external_id not in snapshot_ids and existing.is_current and existing.deleted_at is None:
            existing.is_current = False
            existing.deleted_at = datetime.now(UTC)
            removed_ids.add(existing.id)
            run.items_removed += 1
    if removed_ids:
        scrub_item_derivatives(session, owner_id, removed_ids, commit=False)
        mark_item_evidence_unavailable(
            session,
            owner_id=owner_id,
            item_ids=removed_ids,
            availability="deleted",
        )
    return persisted, deletion_document


def ingest_file(
    *,
    session: Session,
    store: ObjectStore,
    source: SourceConnection,
    owner_id: str,
    filename: str,
    content_type: str,
    payload: bytes,
    conversation_ids: set[str] | None = None,
    captured_at: datetime | None = None,
    source_timezone: str | None = None,
    user_timezone: str = "UTC",
    defer_photo_ocr: bool = False,
    desktop_file_key: str | None = None,
    desktop_relative_path: str | None = None,
    desktop_config: Settings | None = None,
) -> tuple[SyncRun, list[SourceItem]]:
    if source.owner_id != owner_id:
        raise IngestionFailure("source_not_found", "The selected source was not found.", 404)
    if source.kind == "calendar_ics":
        locked_source = session.execute(
            select(SourceConnection)
            .where(SourceConnection.id == source.id, SourceConnection.owner_id == owner_id)
            .with_for_update()
        ).scalar_one_or_none()
        if locked_source is None:
            raise IngestionFailure("source_not_found", "The selected source was not found.", 404)
        source = locked_source
    if source.status != "active":
        raise IngestionFailure("source_not_active", "Resume this source before importing.", 409)

    file_hash = hashlib.sha256(payload).hexdigest()
    run = SyncRun(
        owner_id=owner_id,
        source_id=source.id,
        status="processing",
        file_sha256=file_hash,
    )
    session.add(run)
    session.flush()

    stored_object_key: str | None = None
    try:
        parsed_items, parser_version, stored_payload, stored_content_type = _parser_for(
            source,
            payload,
            filename,
            content_type,
            conversation_ids,
            captured_at,
            source_timezone,
            user_timezone,
            defer_photo_ocr,
        )
        run.parser_version = parser_version
        if desktop_file_key is not None:
            parsed_items = [
                replace(
                    item,
                    external_id=f"desktop:{desktop_file_key}:" + hashlib.sha256(
                        item.external_id.encode("utf-8"),
                    ).hexdigest(),
                    source_locator={**item.source_locator, "file": desktop_relative_path},
                )
                for item in parsed_items
            ]
        run.items_seen = len(parsed_items)
        stored_hash = hashlib.sha256(stored_payload).hexdigest()
        object_key = f"owners/{owner_id}/sources/{source.id}/{stored_hash}/source.bin"
        stored_object_key = object_key
        store.put(object_key, stored_payload, stored_content_type or "application/octet-stream")
        run.object_key = object_key
        persisted: list[SourceItem] = []
        deletion_document: dict | None = None

        if source.kind == "calendar_ics":
            persisted, deletion_document = _persist_calendar_items(
                session=session,
                source=source,
                owner_id=owner_id,
                run=run,
                parsed_items=parsed_items,
                stored_hash=stored_hash,
                object_key=object_key,
                parser_version=parser_version,
                store=store,
            )
        else:
            for parsed in parsed_items:
                record_hash = _record_hash(parsed)
                existing_current = session.scalar(
                    select(SourceItem).where(
                        SourceItem.owner_id == owner_id,
                        SourceItem.source_id == source.id,
                        SourceItem.external_id == parsed.external_id,
                        SourceItem.is_current.is_(True),
                    )
                )
                session.execute(
                    update(SourceItem)
                    .where(
                        SourceItem.owner_id == owner_id,
                        SourceItem.source_id == source.id,
                        SourceItem.external_id == parsed.external_id,
                        SourceItem.is_current.is_(True),
                        SourceItem.source_sha256 != record_hash,
                    )
                    .values(is_current=False)
                )
                item_id = new_id()
                values = {
                    "id": item_id,
                    "owner_id": owner_id,
                    "source_id": source.id,
                    "sync_run_id": run.id,
                    "external_id": parsed.external_id,
                    "kind": parsed.kind,
                    "title": parsed.title[:500],
                    "content_text": parsed.content_text,
                    "occurred_at": parsed.occurred_at,
                    "source_timezone": parsed.source_timezone,
                    "source_sha256": record_hash,
                    "stored_sha256": stored_hash,
                    "parser_version": parser_version,
                    "object_key": object_key,
                    "source_locator": parsed.source_locator,
                    "metadata_json": {**parsed.metadata, "content_type": parsed.metadata.get("media_type", stored_content_type)},
                    "is_current": True,
                }
                if _insert_source_item(session, values):
                    run.items_created += 1
                    item = session.get(SourceItem, item_id)
                    if item is not None:
                        if existing_current is not None:
                            _copy_item_organization(session, existing_current.id, item.id)
                        persisted.append(item)
                else:
                    run.items_duplicate += 1
                    existing = session.scalar(
                        select(SourceItem).where(
                            SourceItem.owner_id == owner_id,
                            SourceItem.source_id == source.id,
                            SourceItem.external_id == parsed.external_id,
                            SourceItem.source_sha256 == record_hash,
                        )
                    )
                    if existing is not None:
                        if desktop_file_key and existing.deleted_at is None:
                            existing.is_current = True
                        persisted.append(existing)

        pending_ocr_items = [
            item
            for item in persisted
            if item.kind == "photo" and item.metadata_json.get("ocr_status") == "pending"
        ]
        for item in pending_ocr_items:
            job = enqueue_background_job(
                session,
                owner_id=owner_id,
                source_id=source.id,
                source_item_id=item.id,
                sync_run_id=run.id,
                kind="photo_ocr",
                dedupe_key=f"photo-ocr:{run.id}:{item.id}",
                payload={"source_item_id": item.id},
            )
            item.metadata_json = {**item.metadata_json, "ocr_job_id": job.id}
        if (desktop_config is not None and desktop_config.app_env == "desktop"
                and source.cloud_consent_at
                and source.cloud_consent_version == desktop_config.graph_cloud_consent_version):
            for item in persisted:
                if item.sync_run_id == run.id and item.content_text.strip() and item.kind != "photo":
                    enqueue_background_job(
                        session, owner_id=owner_id, source_id=source.id, source_item_id=item.id,
                        kind="desktop_analysis", dedupe_key=f"desktop-analysis:{item.id}",
                        payload={"provider": "desktop"},
                    )
        if pending_ocr_items:
            run.status = "processing"
            run.completed_at = None
        else:
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            source.last_sync_at = run.completed_at
        session.commit()
        session.refresh(run)
        if deletion_document is not None:
            try:
                complete_item_deletion(store, owner_id, deletion_document)
            except Exception as cleanup_error:  # noqa: BLE001 - startup replays the durable request.
                logger.warning("Failed to complete item deletion journal: %s", type(cleanup_error).__name__)
        return run, persisted
    except IngestionFailure as error:
        session.rollback()
        failed_run = SyncRun(
            owner_id=owner_id,
            source_id=source.id,
            status="failed",
            file_sha256=file_hash,
            items_failed=1,
            error_code=error.code,
            completed_at=datetime.now(UTC),
        )
        session.add(failed_run)
        session.commit()
        raise
    except Exception:
        session.rollback()
        if stored_object_key:
            try:
                store.delete(stored_object_key)
            except Exception as cleanup_error:  # noqa: BLE001 - preserve the original import failure.
                logger.warning("Failed to clean up an unreferenced upload: %s", type(cleanup_error).__name__)
        raise


def response_item(item: SourceItem) -> dict:
    text = item.content_text
    description = item.metadata_json.get("user_description")
    if isinstance(description, str) and description.strip():
        text = (text + "\n\nPhoto description (user-confirmed):\n" + description.strip()).strip()
    return {
        "id": item.id,
        "source_id": item.source_id,
        "sync_run_id": item.sync_run_id,
        "kind": item.kind,
        "title": item.title,
        "content_text": text,
        "occurred_at": item.occurred_at,
        "source_timezone": item.source_timezone,
        "source_locator": item.source_locator,
        "metadata": item.metadata_json,
        "created_at": item.created_at,
    }
