"""Scoped polling of desktop Markdown folders and read-only Obsidian vaults."""

import hashlib
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from stat import FILE_ATTRIBUTE_REPARSE_POINT
from threading import Event, RLock

from sqlalchemy import select

from personal_ai_life_os.models import (
    DesktopFolder,
    DesktopFolderFile,
    SourceConnection,
    SourceItem,
)
from personal_ai_life_os.parsers.streaming_chat import (
    ChatExportCancelled,
    ChatExportError,
    stage_selected_conversations,
    stream_conversations,
)
from personal_ai_life_os.services.graph_evidence import mark_item_evidence_unavailable
from personal_ai_life_os.services.ingestion import IngestionFailure, ingest_file

logger = logging.getLogger(__name__)
EXCLUDED_DIRECTORIES = {".obsidian", ".git", ".trash", "$recycle.bin", "system volume information", "lifeos-exports"}


def path_key(value: str) -> str:
    return hashlib.sha256(os.path.normcase(value).encode("utf-8")).hexdigest()


def scoped_file_stat(path: Path):
    record = path.lstat()
    if path.is_symlink() or getattr(record, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("Links and Windows reparse points are excluded from synchronization.")
    return record


def _stamp(path: Path) -> str:
    stat = scoped_file_stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_dev}:{stat.st_ino}"


def _scoped_chat_file(root: Path, file: Path) -> Path:
    relative = file.relative_to(root)
    candidate = root
    scoped_file_stat(candidate)
    for part in relative.parts:
        candidate /= part
        scoped_file_stat(candidate)
    if not candidate.is_file() or candidate.resolve(strict=True) != candidate:
        raise ValueError("The selected file is outside the authorized chat directory.")
    return relative


def _markdown_files(root: Path):
    scoped_file_stat(root)
    if root.resolve(strict=True) != root or not root.is_dir():
        raise OSError("Folder is unavailable.")

    def on_error(error: OSError):
        raise error

    for current, directories, filenames in os.walk(root, onerror=on_error, followlinks=False):
        parents = Path(current)
        allowed = []
        for name in sorted(directories):
            if name.casefold() in EXCLUDED_DIRECTORIES or name.startswith("."):
                continue
            try:
                scoped_file_stat(parents / name)
            except ValueError:
                continue
            allowed.append(name)
        directories[:] = allowed
        for name in sorted(filenames):
            candidate = parents / name
            if name.startswith(".") or candidate.suffix.lower() not in {".md", ".markdown"}:
                continue
            try:
                fingerprint = _stamp(candidate)
            except ValueError:
                continue
            if candidate.resolve(strict=True).is_relative_to(root) and candidate.is_file():
                yield candidate, candidate.relative_to(root).as_posix(), fingerprint


def file_items(session, source_id: str, file_key: str):
    return session.scalars(select(SourceItem).where(
        SourceItem.source_id == source_id,
        SourceItem.external_id.startswith(f"desktop:{file_key}:"),
        SourceItem.deleted_at.is_(None),
    ))


def _exclude_items(session, source: SourceConnection, items: list[SourceItem], availability: str):
    ids = {item.id for item in items if item.is_current}
    for item in items:
        item.is_current = False
    mark_item_evidence_unavailable(
        session, owner_id=source.owner_id, item_ids=ids, availability=availability,
    )


def _ingest_selected_chat(session, store, config, source, staged, key, relative, canceled):
    current_ids = set()
    count = 0
    for _, _, staged_path in staged:
        if canceled.is_set():
            raise ChatExportCancelled()
        session.refresh(source)
        if source.status != "active":
            raise ChatExportError("Resume the chat folder before reimporting.")
        run, items = ingest_file(
            session=session, store=store, source=source, owner_id=source.owner_id,
            filename="conversations.json",
            content_type="application/json", payload=staged_path.read_bytes(),
            user_timezone=source.owner.timezone, desktop_file_key=key, desktop_relative_path=relative,
            desktop_config=config,
        )
        count += run.items_created
        current_ids.update(item.id for item in items)
    _exclude_items(session, source, [
        item for item in file_items(session, source.id, key) if item.id not in current_ids
    ], "superseded")
    return count


def register_chat_watch(application, owner_id, folder_id, file, selected, records, canceled):
    manager = application.state.desktop_folders
    factory = application.state.session_factory
    with factory() as session:
        folder = session.get(DesktopFolder, folder_id)
        source = session.get(SourceConnection, folder_id)
        if (folder is None or folder.kind != "chat_folder" or source is None
                or source.owner_id != owner_id or source.status != "active"):
            raise ChatExportError("Choose an active authorized chat folder.")
        root = Path(folder.path)
    try:
        relative = _scoped_chat_file(root, file).as_posix()
        fingerprint = _stamp(file)
    except (OSError, ValueError) as error:
        raise ChatExportError("The export must be within the selected chat folder.") from error
    key = path_key(relative)
    with stage_selected_conversations(records, selected) as staged:
        if len(staged) != len(selected) or _stamp(file) != fingerprint:
            raise ChatExportError("The chat export changed. Open it again before importing.")
        with manager.mutation_lock, factory() as session:
            source = session.get(SourceConnection, folder_id)
            if source is None or source.status != "active":
                raise ChatExportError("Resume the authorized chat folder before importing.")
            entry = session.scalar(select(DesktopFolderFile).where(
                DesktopFolderFile.source_id == folder_id, DesktopFolderFile.file_key == key,
            ))
            if entry is not None and entry.status != "active":
                raise ChatExportError("Review the file’s pending deletion in the inbox.")
            count = _ingest_selected_chat(
                session, application.state.object_store, application.state.settings,
                source, staged, key, relative, canceled,
            )
            if entry is None:
                entry = DesktopFolderFile(
                    source_id=folder_id, file_key=key, relative_path=relative, fingerprint=fingerprint,
                )
                session.add(entry)
            entry.conversation_ids = sorted(selected)
            entry.fingerprint = fingerprint
            session.commit()
            return count


class DesktopFolderSync:
    def __init__(self):
        self.mutation_lock = RLock()

    def run(self, session_factory, store, config, stop: Event):
        while not stop.is_set():
            try:
                with session_factory() as session:
                    source_ids = list(session.scalars(
                        select(DesktopFolder.source_id).join(SourceConnection).where(
                            SourceConnection.status == "active",
                        ),
                    ))
                for source_id in source_ids:
                    if stop.is_set():
                        break
                    self._scan(session_factory, store, config, stop, source_id)
            except Exception as error:  # noqa: BLE001 - a recoverable poll must not stop the watcher.
                logger.warning("Folder synchronization could not complete a scan (%s).", type(error).__name__)
            stop.wait(3)

    def _scan(self, session_factory, store, config, stop: Event, source_id: str):
        with session_factory() as session:
            folder = session.get(DesktopFolder, source_id)
            if folder is None:
                return
            root = Path(folder.path)
            if folder.kind == "chat_folder":
                self._scan_chat(session_factory, store, config, stop, source_id, root)
                return
        seen = set()
        errors = False
        try:
            for file, relative, fingerprint in _markdown_files(root):
                if stop.is_set():
                    return
                key = path_key(relative)
                seen.add(key)
                with self.mutation_lock, session_factory() as session:
                    source = session.get(SourceConnection, source_id)
                    if source is None or source.status != "active":
                        return
                    try:
                        self._sync_file(session, store, config, source, file, relative, key, fingerprint)
                    except (OSError, ValueError, IngestionFailure):
                        errors = True
        except (OSError, ValueError):
            # An unavailable root or interrupted scan cannot establish that files disappeared.
            self._finish_scan(session_factory, source_id, None, "unavailable")
            return
        self._finish_scan(session_factory, source_id, seen, "partial" if errors else "up_to_date")

    def _scan_chat(self, session_factory, store, config, stop, source_id, root):
        if not root.is_dir() or root.resolve() != root:
            self._finish_scan(session_factory, source_id, None, "unavailable")
            return
        with session_factory() as session:
            entries = list(session.scalars(select(DesktopFolderFile).where(
                DesktopFolderFile.source_id == source_id, DesktopFolderFile.status == "active",
            )))
        seen = set()
        errors = False
        for entry in entries:
            if stop.is_set():
                return
            file = root / entry.relative_path
            try:
                _scoped_chat_file(root, file)
                fingerprint = _stamp(file)
                seen.add(entry.file_key)
                if fingerprint == entry.fingerprint:
                    continue
                with stage_selected_conversations(
                    stream_conversations(file, canceled=stop.is_set), set(entry.conversation_ids),
                ) as staged:
                    if _stamp(file) != fingerprint:
                        raise ChatExportError("The export changed during the current scan.")
                    with self.mutation_lock, session_factory() as session:
                        active = session.get(DesktopFolderFile, entry.id)
                        source = session.get(SourceConnection, source_id)
                        if source is None or source.status != "active":
                            return
                        if (active is None or active.status != "active"
                                or active.conversation_ids != entry.conversation_ids
                                or active.fingerprint != entry.fingerprint):
                            continue
                        _ingest_selected_chat(
                            session, store, config, source, staged, entry.file_key, entry.relative_path, stop,
                        )
                        active.fingerprint = fingerprint
                        session.commit()
            except FileNotFoundError:
                if not root.is_dir():
                    self._finish_scan(session_factory, source_id, None, "unavailable")
                    return
            except ChatExportCancelled:
                return
            except (OSError, ValueError, IngestionFailure):
                seen.add(entry.file_key)
                errors = True
        self._finish_scan(
            session_factory, source_id, seen, "partial" if errors else "up_to_date",
            checked={entry.file_key for entry in entries},
        )

    def _sync_file(self, session, store, config, source, file, relative, key, fingerprint):
        entry = session.scalar(select(DesktopFolderFile).where(
            DesktopFolderFile.source_id == source.id,
            DesktopFolderFile.file_key == key,
        ))
        if entry is not None and (entry.fingerprint == fingerprint or entry.status != "active"):
            return
        with file.open("rb") as stream:
            content = stream.read(config.max_text_upload_bytes + 1)
        if len(content) > config.max_text_upload_bytes or _stamp(file) != fingerprint:
            raise ValueError("The file is too large or changed during the scan.")
        if source.selected_scope.get("desktop_folder_kind") == "obsidian" and (
            b"lifeos_id:" in content[:8192] or b"lifeos_kind:" in content[:8192]
        ):
            return
        _, current = ingest_file(
            session=session, store=store, source=source, owner_id=source.owner_id,
            filename=file.name, content_type="text/markdown", payload=content,
            user_timezone=source.owner.timezone, desktop_file_key=key, desktop_relative_path=relative,
            desktop_config=config,
        )
        current_ids = {item.id for item in current}
        _exclude_items(
            session, source,
            [item for item in file_items(session, source.id, key) if item.id not in current_ids],
            "superseded",
        )
        if entry is None:
            session.add(DesktopFolderFile(
                source_id=source.id, relative_path=relative, file_key=key, fingerprint=fingerprint,
            ))
        else:
            entry.fingerprint = fingerprint
        session.commit()

    def _finish_scan(self, session_factory, source_id, seen, status, *, checked=None):
        with self.mutation_lock, session_factory() as session:
            source = session.get(SourceConnection, source_id)
            folder = session.get(DesktopFolder, source_id)
            if source is None or folder is None or source.status != "active":
                return
            if seen is not None:
                for entry in session.scalars(select(DesktopFolderFile).where(
                    DesktopFolderFile.source_id == source_id,
                    DesktopFolderFile.status == "active",
                )):
                    if entry.file_key not in seen and (checked is None or entry.file_key in checked):
                        entry.status = "pending_delete"
                        _exclude_items(
                            session, source, list(file_items(session, source.id, entry.file_key)),
                            "source_missing",
                        )
            folder.last_scan_at = datetime.now(UTC)
            folder.scan_status = status
            session.commit()
