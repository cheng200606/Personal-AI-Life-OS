"""Credential-free snapshots and offline replacement of desktop workspace data."""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Event, RLock
from zipfile import ZIP_DEFLATED, ZipFile

logger = logging.getLogger(__name__)
DATABASE = "data/lifeos.db"
ARCHIVE_FORMAT = "lifeos-desktop-backup-1"
MAX_ARCHIVE_EXPANDED = 20 * 1024**3
KEEP_BACKUPS = 7


def write_json(path: Path, payload: dict):
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _absolute_object(root: Path, key: str) -> Path:
    member = PurePosixPath(key)
    if (member.is_absolute() or not member.parts or ".." in member.parts or "\\" in key
            or ":" in key or member.as_posix() != key):
        raise ValueError("Invalid backup member path.")
    candidate = root.joinpath(*member.parts)
    if candidate.resolve() != candidate or not candidate.is_relative_to(root):
        raise ValueError("Links and directory escapes are excluded from backups.")
    return candidate


def _object_keys(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as reader:
        return {key for key, in reader.execute(
            "SELECT DISTINCT object_key FROM source_items WHERE deleted_at IS NULL",
        ) if key}


class DesktopBackup:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.settings = self.root / "backup-settings.json"
        self.lock = RLock()
        fingerprint = os.path.normcase(str(self.root)).encode("utf-8")
        self.prefix = "LifeOS-" + hashlib.sha256(fingerprint).hexdigest()[:12] + "-"
        self.last_error: str | None = None

    def _dest(self) -> Path | None:
        if self.settings.is_file():
            return Path(json.loads(self.settings.read_text(encoding="utf-8"))["path"])
        return None

    def configure(self, directory: Path):
        if (not directory.is_dir() or directory == Path(directory.anchor)
                or directory.is_relative_to(self.root) or self.root.is_relative_to(directory)):
            raise ValueError("Choose a dedicated backup directory outside Life OS data.")
        with self.lock:
            write_json(self.settings, {"path": str(directory)})
            self.last_error = None

    def public(self) -> dict:
        with self.lock:
            dest = self._dest()
            archives = self._archives(dest) if dest and dest.is_dir() else []
            return {
                "path": str(dest) if dest else None,
                "latest": archives[-1].name if archives else None,
                "available": bool(dest and dest.is_dir()),
                "error": self.last_error,
            }

    def _archives(self, dest: Path) -> list[Path]:
        return sorted(path for path in dest.glob(f"{self.prefix}*.zip")
                      if path.is_file() and not path.is_symlink())

    def run(self, stop: Event):
        while not stop.is_set():
            try:
                with self.lock:
                    dest = self._dest()
                    if dest and dest.is_dir():
                        archives = self._archives(dest)
                        today = datetime.now(UTC)
                        cutoff = (today - timedelta(days=1)).timestamp()
                        if not archives or archives[-1].stat().st_mtime < cutoff:
                            self.snapshot()
                    elif dest:
                        self.last_error = "Backup directory is unavailable."
            except (OSError, sqlite3.Error, ValueError) as error:
                self.last_error = "Automatic backup failed. Check the destination and retry."
                logger.warning("Desktop backup failed (%s).", type(error).__name__)
            stop.wait(60)

    def snapshot(self) -> str:
        with self.lock:
            dest = self._dest()
            if dest is None or not dest.is_dir() or dest.resolve(strict=True) != dest:
                raise ValueError("Choose an available backup directory.")
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            destination = dest / f"{self.prefix}{stamp}.zip"
            with TemporaryDirectory(prefix="lifeos-snapshot-", dir=self.root) as directory:
                copy = Path(directory) / "lifeos.db"
                with closing(sqlite3.connect(self.root / DATABASE)) as source, closing(sqlite3.connect(copy)) as sink:
                    source.backup(sink)
                with NamedTemporaryFile(dir=dest, suffix=".partial", delete=False) as stream:
                    incomplete = Path(stream.name)
                try:
                    with ZipFile(incomplete, "w", ZIP_DEFLATED, compresslevel=3) as archive:
                        archive.writestr("manifest.json", json.dumps({"format": ARCHIVE_FORMAT, "created_at": stamp}))
                        archive.write(copy, DATABASE)
                        for key in sorted(_object_keys(copy)):
                            path = _absolute_object(self.root, f"objects/{key}")
                            archive.write(path, f"objects/{key}")
                        journal = self.root / "objects" / ".deletion-tombstones"
                        if journal.is_dir():
                            for entry in journal.glob("*/*.json"):
                                key = entry.relative_to(self.root).as_posix()
                                archive.write(_absolute_object(self.root, key), key)
                    incomplete.replace(destination)
                finally:
                    incomplete.unlink(missing_ok=True)
            for old in self._archives(dest)[:-KEEP_BACKUPS]:
                old.unlink()
            self.last_error = None
            return destination.name

    def stage_restore(self, backup: Path):
        with self.lock:
            stage = self.root / "restore-stage"
            marker = self.root / "restore-request.json"
            if marker.exists():
                raise ValueError("A restore is already waiting for restart.")
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir()
            try:
                with ZipFile(backup) as archive:
                    entries = archive.infolist()
                    names = {entry.filename for entry in entries}
                    if (len(names) != len(entries) or len(entries) > 100_000
                            or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_EXPANDED
                            or not {"manifest.json", DATABASE}.issubset(names)):
                        raise ValueError("Unsupported or oversized desktop backup.")
                    if archive.getinfo("manifest.json").file_size > 4096:
                        raise ValueError("Invalid backup manifest.")
                    if json.loads(archive.read("manifest.json")).get("format") != ARCHIVE_FORMAT:
                        raise ValueError("Unknown backup format.")
                    (stage / "objects").mkdir()
                    for entry in entries:
                        name = entry.filename
                        if name == "manifest.json":
                            continue
                        if name != DATABASE and not name.startswith(("objects/owners/", "objects/.deletion-tombstones/")):
                            raise ValueError("Unexpected backup member.")
                        destination = _absolute_object(stage, name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as source, destination.open("xb") as sink:
                            shutil.copyfileobj(source, sink, 1024 * 1024)
                self._prepare_restored_data(stage)
                write_json(marker, {"format": ARCHIVE_FORMAT})
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise

    def _prepare_restored_data(self, stage: Path):
        database = stage / DATABASE
        for key in _object_keys(database):
            if not _absolute_object(stage, f"objects/{key}").is_file():
                raise ValueError("The backup is missing source objects.")
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("The backup database failed its integrity check.")
            connection.execute(
                "UPDATE source_connections SET status='paused' WHERE status='active' "
                "AND id IN (SELECT source_id FROM desktop_folders)",
            )
            connection.execute("UPDATE source_connections SET cloud_consent_at=NULL, cloud_consent_version=NULL")
            connection.execute("DELETE FROM model_consents")
            connection.execute(
                "UPDATE users SET ai_consent_at=NULL, ai_consent_provider=NULL, ai_consent_disclosure_version=NULL",
            )
            connection.execute(
                "UPDATE background_jobs SET status='cancelled', worker_id=NULL, lease_expires_at=NULL, "
                "error_code='backup_restored' WHERE status IN ('running','queued') AND kind!='photo_ocr'",
            )
            connection.commit()

    def prepare_startup(self) -> bool:
        stage = self.root / "restore-stage"
        rollback = self.root / "restore-rollback"
        marker = self.root / "restore-request.json"
        if rollback.exists():
            if marker.exists():
                self.rollback_restore()
            else:
                shutil.rmtree(rollback)
        if not marker.is_file():
            return False
        journal = self.root / "objects" / ".deletion-tombstones"
        if journal.is_dir():
            for entry in journal.glob("*/*.json"):
                relative = entry.relative_to(self.root).as_posix()
                target = _absolute_object(stage, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(_absolute_object(self.root, relative), target)
        rollback.mkdir()
        try:
            for directory in ("data", "objects"):
                active = self.root / directory
                if active.exists():
                    active.rename(rollback / directory)
                (stage / directory).rename(active)
        except OSError:
            self.rollback_restore()
            raise
        return True

    def finish_restore(self):
        (self.root / "restore-request.json").unlink(missing_ok=True)
        shutil.rmtree(self.root / "restore-rollback", ignore_errors=True)
        shutil.rmtree(self.root / "restore-stage", ignore_errors=True)

    def rollback_restore(self):
        rollback = self.root / "restore-rollback"
        for directory in ("data", "objects"):
            previous = rollback / directory
            if previous.exists():
                active = self.root / directory
                if active.exists():
                    shutil.rmtree(active)
                previous.rename(active)
        self.finish_restore()
