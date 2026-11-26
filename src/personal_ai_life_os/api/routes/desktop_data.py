"""Explicit native backup, restore and Markdown export actions."""

import re
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from zipfile import BadZipFile

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from personal_ai_life_os.api.deps import CurrentUserDep
from personal_ai_life_os.api.routes.desktop_chats import PathGrant, verify_path_grant
from personal_ai_life_os.services.desktop_folders import scoped_file_stat

router = APIRouter(prefix="/desktop/data", tags=["desktop"])
INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)),
                   *("LPT" + str(i) for i in range(1, 10))}


class MarkdownExport(BaseModel):
    grant: PathGrant
    filename: str = Field(min_length=1, max_length=160)
    markdown: str = Field(max_length=5_000_000)
    policy: Literal["keep", "copy", "overwrite"]


def _selected(grant: PathGrant, request: Request, purpose: str) -> Path:
    return verify_path_grant(grant, request.app.state.desktop_chats.path_key, purpose)


@router.get("/backup")
def backup_status(request: Request, user: CurrentUserDep) -> dict:
    return request.app.state.desktop_backup.public()


@router.put("/backup")
def set_backup(grant: PathGrant, request: Request, user: CurrentUserDep) -> dict:
    directory = _selected(grant, request, "backup")
    service = request.app.state.desktop_backup
    try:
        service.configure(directory)
    except (OSError, ValueError) as error:
        raise HTTPException(422, str(error)) from None
    return service.public()


@router.post("/backup")
def backup_now(request: Request, user: CurrentUserDep) -> dict:
    try:
        return {"filename": request.app.state.desktop_backup.snapshot()}
    except (OSError, sqlite3.Error, ValueError):
        raise HTTPException(422, "Backup could not be written. Check the destination and available space.") from None


@router.post("/restore", status_code=202)
def schedule_restore(grant: PathGrant, request: Request, user: CurrentUserDep) -> dict:
    selected = _selected(grant, request, "restore")
    if not selected.is_file() or selected.suffix.lower() != ".zip":
        raise HTTPException(422, "Choose a Life OS backup ZIP.")
    try:
        request.app.state.desktop_backup.stage_restore(selected)
    except (BadZipFile, OSError, sqlite3.Error, ValueError):
        raise HTTPException(422, "This backup could not be validated. Current data is still active.") from None
    return {"restart_required": True}


@router.post("/export")
def export_to_folder(payload: MarkdownExport, request: Request, user: CurrentUserDep) -> dict:
    root = _selected(payload.grant, request, "export")
    data = request.app.state.settings.data_dir.resolve()
    filename = payload.filename
    if (not root.is_dir() or root.is_relative_to(data) or data.is_relative_to(root)
            or INVALID_NAME.search(filename) or filename.startswith(".") or filename != filename.strip()
            or not filename.lower().endswith(".md") or filename.split(".")[0].upper() in WINDOWS_DEVICES):
        raise HTTPException(422, "Choose a valid Markdown name and an export directory outside Life OS data.")
    try:
        folder = root / "LifeOS-Exports"
        folder.mkdir(exist_ok=True)
        scoped_file_stat(folder)
        if folder.resolve() != folder:
            raise ValueError("Export directory is a link.")
        target = folder / filename
        if target.exists() and payload.policy == "keep":
            return {"status": "kept", "filename": filename}
        if payload.policy == "copy":
            index = 1
            while target.exists():
                target = folder / f"{Path(filename).stem}-{index}.md"
                index += 1
        temporary_path = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload.markdown)
            if payload.policy == "overwrite":
                temporary_path.replace(target)
            else:
                temporary_path.rename(target)  # Windows refuses to replace an existing file here.
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
    except (OSError, ValueError):
        raise HTTPException(422, "The selected destination could not be written.") from None
    return {"status": "written", "filename": target.name}
