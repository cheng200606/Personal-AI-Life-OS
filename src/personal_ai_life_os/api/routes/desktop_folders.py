"""Native folder authorization and review of missing source files."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.routes.desktop_chats import PathGrant, verify_path_grant
from personal_ai_life_os.models import DesktopFolder, DesktopFolderFile, SourceConnection
from personal_ai_life_os.services.deletion import (
    complete_item_deletion,
    erase_desktop_file_records,
    remove_desktop_file_objects,
    request_item_deletions,
)
from personal_ai_life_os.services.desktop_folders import file_items, path_key

router = APIRouter(prefix="/desktop/folders", tags=["desktop"])


class FolderSelection(BaseModel):
    kind: Literal["markdown", "obsidian", "chat_folder"]
    grant: PathGrant


def _folder_response(folder: DesktopFolder, source: SourceConnection) -> dict:
    return {
        "id": folder.source_id, "name": source.name, "path": folder.path,
        "kind": folder.kind, "status": source.status, "scan_status": folder.scan_status,
        "last_scan_at": folder.last_scan_at,
    }


@router.get("")
def list_folders(user: CurrentUserDep, session: SessionDep) -> list[dict]:
    return [
        _folder_response(folder, source)
        for folder, source in session.execute(
            select(DesktopFolder, SourceConnection).join(SourceConnection).where(
                SourceConnection.owner_id == user.id,
                SourceConnection.status.in_(("active", "paused")),
            ).order_by(SourceConnection.name),
        )
    ]


@router.post("", status_code=201)
def add_folder(payload: FolderSelection, request: Request, user: CurrentUserDep, session: SessionDep) -> dict:
    path = verify_path_grant(payload.grant, request.app.state.desktop_chats.path_key, payload.kind)
    root = request.app.state.settings.data_dir.resolve()
    if not path.is_dir() or path == Path(path.anchor) or root.is_relative_to(path) or path.is_relative_to(root):
        raise HTTPException(422, "Choose a specific folder outside the application data directory.")
    key = path_key(str(path))
    existing = session.execute(
        select(DesktopFolder, SourceConnection).join(SourceConnection).where(
            DesktopFolder.path_key == key, SourceConnection.owner_id == user.id,
        ),
    ).one_or_none()
    if existing:
        folder, source = existing
        if source.status != "revoked" or folder.kind != payload.kind:
            raise HTTPException(409, "This folder is already authorized or uses another source type.")
        source.status = "active"
        source.cloud_consent_at = source.cloud_consent_version = None
        folder.scan_status = "waiting"
        session.commit()
        return _folder_response(folder, source)
    source = SourceConnection(
        owner_id=user.id, kind="chat_export" if payload.kind == "chat_folder" else "memory_markdown",
        name=path.name[:240], selected_scope={"desktop_folder_kind": payload.kind}, consent_version="desktop-folder-v1",
    )
    session.add(source)
    session.flush()
    folder = DesktopFolder(
        source_id=source.id, path=str(path), path_key=key, kind=payload.kind,
    )
    session.add(folder)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "This folder is already authorized.") from error
    return _folder_response(folder, source)


@router.get("/missing")
def list_missing(user: CurrentUserDep, session: SessionDep) -> list[dict]:
    return [
        {"id": entry.id, "path": entry.relative_path, "source": source.name}
        for entry, source in session.execute(
            select(DesktopFolderFile, SourceConnection)
            .join(SourceConnection, SourceConnection.id == DesktopFolderFile.source_id)
            .where(DesktopFolderFile.status == "pending_delete", SourceConnection.owner_id == user.id)
            .order_by(SourceConnection.name, DesktopFolderFile.relative_path),
        )
    ]


@router.delete("/missing/{entry_id}", status_code=204)
def delete_missing(entry_id: str, request: Request, user: CurrentUserDep, session: SessionDep) -> None:
    with request.app.state.desktop_folders.mutation_lock:
        row = session.execute(
            select(DesktopFolderFile, SourceConnection)
            .join(SourceConnection, SourceConnection.id == DesktopFolderFile.source_id)
            .where(DesktopFolderFile.id == entry_id, SourceConnection.owner_id == user.id),
        ).one_or_none()
        if row is None:
            raise HTTPException(404, "The selected file was not found.")
        entry, source = row
        if entry.status == "deleted":
            return
        if entry.status != "pending_delete":
            raise HTTPException(409, "The selected file is not pending deletion.")
        items = list(file_items(session, source.id, entry.file_key))
        ids = {item.id for item in items}
        store = request.app.state.object_store
        document = request_item_deletions(
            store, user.id, ids, tombstone_id=entry.id, desktop_file_id=entry.id,
            object_keys={item.object_key for item in items if item.object_key},
        ) if ids else None
        erase_desktop_file_records(session, user.id, items)
        entry.status = "deleted"
        if document:
            session.flush()
            remove_desktop_file_objects(session, store, document)
        session.commit()
        if document:
            complete_item_deletion(store, user.id, document)
