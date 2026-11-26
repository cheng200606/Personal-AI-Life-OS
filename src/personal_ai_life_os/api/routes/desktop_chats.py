"""Large desktop chat imports, accessible only through a native file selection."""

import hashlib
import hmac
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from time import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep
from personal_ai_life_os.models import SourceConnection
from personal_ai_life_os.parsers.streaming_chat import (
    ChatExportCancelled,
    ChatExportError,
    stage_selected_conversations,
    stream_conversations,
)
from personal_ai_life_os.services.desktop_folders import register_chat_watch
from personal_ai_life_os.services.ingestion import IngestionFailure, ingest_file

router = APIRouter(prefix="/desktop/chats", tags=["desktop"])
logger = logging.getLogger(__name__)
MAX_SESSIONS = 8
MAX_CONVERSATIONS = 50_000


class PathGrant(BaseModel):
    payload: str = Field(max_length=36_000)
    signature: str = Field(min_length=64, max_length=64)


class ChatSelection(BaseModel):
    conversation_ids: set[str] = Field(min_length=1, max_length=MAX_CONVERSATIONS)
    folder_id: str | None = None


@dataclass
class ChatSession:
    owner_id: str
    path: Path
    fingerprint: tuple[int, int, int, int]
    id: str = field(default_factory=lambda: uuid4().hex)
    state: str = "previewing"
    bytes_read: int = 0
    rows: list[dict] = field(default_factory=list)
    items_created: int = 0
    error: str | None = None
    cancel: Event = field(default_factory=Event)


class ChatSessions:
    def __init__(self, path_key: bytes):
        self.path_key = path_key
        self.lock = Lock()
        self.sessions: dict[str, ChatSession] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lifeos-chat")

    def close(self):
        with self.lock:
            for task in self.sessions.values():
                task.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def new(self, task: ChatSession):
        with self.lock:
            if len(self.sessions) >= MAX_SESSIONS:
                expired = next((key for key, value in self.sessions.items() if value.state not in {
                    "previewing", "importing",
                }), None)
                if expired is None:
                    raise HTTPException(429, "Wait for a current chat operation to finish.")
                del self.sessions[expired]
            self.sessions[task.id] = task

    def get(self, task_id: str, owner_id: str) -> ChatSession:
        with self.lock:
            task = self.sessions.get(task_id)
            if task is None or task.owner_id != owner_id:
                raise HTTPException(404, "This chat selection expired. Open the export again.")
            return task


def _fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


def verify_path_grant(grant: PathGrant, key: bytes, purpose: str) -> Path:
    signature = hmac.digest(key, grant.payload.encode("utf-8"), "sha256").hex()
    if not hmac.compare_digest(signature.encode("ascii"), grant.signature.encode("utf-8")):
        raise HTTPException(403, "Choose the file in the application’s native picker.")
    try:
        payload = json.loads(grant.payload)
        if payload["purpose"] != purpose or not -3 <= time() - payload["issued"] <= 120:
            raise ValueError()
        path = Path(payload["path"])
        if not path.is_absolute():
            raise ValueError()
        return path.resolve(strict=True)
    except (OSError, KeyError, ValueError, TypeError):
        raise HTTPException(422, "The native selection expired or is unavailable.") from None


def _iter_task(task: ChatSession):
    if _fingerprint(task.path) != task.fingerprint:
        raise ChatExportError("The file has changed. Open it again to review the current conversations.")

    def progress(value: int):
        task.bytes_read = value

    yield from stream_conversations(task.path, progress=progress, canceled=task.cancel.is_set)
    if _fingerprint(task.path) != task.fingerprint:
        raise ChatExportError("The file changed while it was being read. Open it again.")


def _preview(task: ChatSession):
    rows = []
    for identity, record in _iter_task(task):
        if len(rows) >= MAX_CONVERSATIONS:
            raise ChatExportError("This export contains more than 50,000 conversations.")
        title = next((record[key] for key in ("title", "name", "subject")
                      if isinstance(record.get(key), str) and record[key].strip()), identity)
        rows.append({"id": identity, "title": title.strip()[:500]})
    task.rows = rows


def _run(task: ChatSession, operation, success: str, lock: Lock):
    state, error = success, None
    try:
        operation()
    except ChatExportCancelled:
        state = "canceled"
    except (ChatExportError, IngestionFailure) as failure:
        state, error = "failed", str(failure) if isinstance(failure, ChatExportError) else failure.message
    except Exception as failure:  # noqa: BLE001 - retain a retryable task status without logging file contents.
        logger.warning("Desktop chat operation failed (%s).", type(failure).__name__)
        state, error = "failed", "The selected export could not be processed locally."
    with lock:
        task.error = error
        task.state = state


def _import(task: ChatSession, selected: set[str], application, timezone: str, folder_id: str | None):
    if folder_id:
        task.items_created = register_chat_watch(
            application, task.owner_id, folder_id, task.path, selected,
            _iter_task(task), task.cancel,
        )
        return
    with stage_selected_conversations(_iter_task(task), selected) as staged:
        if len(staged) != len(selected):
            raise ChatExportError("The export no longer contains every selected conversation.")

        scope_id = hashlib.sha256(os.path.normcase(str(task.path)).encode("utf-8")).hexdigest()
        store = application.state.object_store
        with application.state.session_factory() as session:
            sources = {
                source.kind: source
                for source in session.scalars(select(SourceConnection).where(
                    SourceConnection.owner_id == task.owner_id,
                    SourceConnection.kind.in_(("chatgpt_export", "chat_export")),
                ))
                if source.selected_scope.get("desktop_path_id") == scope_id
                and source.status != "revoked"
            }
            for identity, is_chatgpt, path in staged:
                if task.cancel.is_set():
                    raise ChatExportCancelled()
                kind = "chatgpt_export" if is_chatgpt else "chat_export"
                source = sources.get(kind)
                if source is None:
                    source = SourceConnection(
                        owner_id=task.owner_id, kind=kind, name=task.path.name[:160],
                        selected_scope={}, consent_version="desktop-chat-v1",
                    )
                    session.add(source)
                    sources[kind] = source
                if source.status not in {None, "active"}:
                    raise ChatExportError("Resume the chat source before reimporting.")
                source.selected_scope = {
                    "desktop_path_id": scope_id,
                    "conversation_ids": sorted(selected),
                }
                session.flush()
                run, _ = ingest_file(
                    session=session, store=store, source=source, owner_id=task.owner_id,
                    filename="conversations.json", content_type="application/json",
                    payload=path.read_bytes(), conversation_ids={identity}, user_timezone=timezone,
                    desktop_config=application.state.settings,
                )
                task.items_created += run.items_created


@router.post("/preview", status_code=202)
def start_preview(grant: PathGrant, request: Request, user: CurrentUserDep) -> dict:
    manager: ChatSessions = request.app.state.desktop_chats
    path = verify_path_grant(grant, manager.path_key, "chat")
    try:
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl"}:
            raise OSError()
        task = ChatSession(user.id, path, _fingerprint(path))
    except OSError:
        raise HTTPException(422, "The selected chat file is unavailable.") from None
    manager.new(task)
    manager.executor.submit(_run, task, lambda: _preview(task), "ready", manager.lock)
    return {"id": task.id}


@router.get("/{task_id}")
def chat_status(
    task_id: str, user: CurrentUserDep, request: Request,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
) -> dict:
    manager: ChatSessions = request.app.state.desktop_chats
    task = manager.get(task_id, user.id)
    with manager.lock:
        return {
            "id": task.id, "filename": task.path.name, "state": task.state,
            "bytes_read": task.bytes_read, "total_bytes": task.fingerprint[0],
            "items_created": task.items_created, "total_conversations": len(task.rows),
            "conversations": task.rows[offset:offset + limit], "error": task.error,
        }


@router.post("/{task_id}/import", status_code=202)
def start_import(
    task_id: str, payload: ChatSelection, request: Request, user: CurrentUserDep,
) -> dict:
    manager: ChatSessions = request.app.state.desktop_chats
    task = manager.get(task_id, user.id)
    with manager.lock:
        if task.state not in {"ready", "complete", "failed", "canceled"}:
            raise HTTPException(409, "Wait for the current chat operation.")
        available = {row["id"] for row in task.rows}
        if not payload.conversation_ids.issubset(available):
            raise HTTPException(422, "Choose conversations from the current file preview.")
        task.state = "importing"
        task.cancel.clear()
        task.bytes_read, task.items_created, task.error = 0, 0, None
    application, timezone = request.app, user.timezone
    manager.executor.submit(
        _run, task, lambda: _import(task, payload.conversation_ids, application, timezone, payload.folder_id),
        "complete", manager.lock,
    )
    return {"id": task.id}


@router.post("/{task_id}/cancel", status_code=202)
def cancel_chat(task_id: str, request: Request, user: CurrentUserDep) -> dict:
    manager: ChatSessions = request.app.state.desktop_chats
    task = manager.get(task_id, user.id)
    task.cancel.set()
    return {"id": task.id}
