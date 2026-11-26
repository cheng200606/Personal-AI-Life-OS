"""Private Windows sidecar process. The launcher owns its stdin and lifetime."""

import json
import logging
import secrets
import socket
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Thread

import uvicorn
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from personal_ai_life_os.config import Settings
from personal_ai_life_os.services.desktop_backup import DesktopBackup

logger = logging.getLogger(__name__)


class DesktopSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings,
    ):
        # Desktop installations must not inherit web/.env or cloud settings.
        return (init_settings,)


def migrate(root: Path, database: Path, config: Settings, assets: Path) -> None:
    from personal_ai_life_os.db import create_database_engine

    migration = Config()
    migration.set_main_option("script_location", str(assets / "migrations").replace("%", "%%"))
    migration.attributes["settings"] = config
    scripts = ScriptDirectory.from_config(migration)
    snapshot = None
    if database.exists():
        engine = create_database_engine(config)
        try:
            with engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_heads()
        finally:
            engine.dispose()
        if set(current) == set(scripts.get_heads()):
            return
        backup_dir = root / "migration-backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot = backup_dir / f"lifeos-{stamp}.sqlite3"
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(
            snapshot,
        )) as backup:
            source.backup(backup)
    try:
        command.upgrade(migration, "head")
    except Exception:
        if snapshot is not None:
            with closing(sqlite3.connect(snapshot)) as previous, closing(sqlite3.connect(database)) as active:
                previous.backup(active)
            logger.error("Database migration failed. The pre-migration snapshot was restored.")
        raise


class DesktopServer(uvicorn.Server):
    restore: DesktopBackup | None = None

    async def startup(self, sockets=None):
        await super().startup(sockets)
        if self.started:
            if self.restore:
                self.restore.finish_restore()
                self.restore = None
            print(json.dumps({"port": sockets[0].getsockname()[1]}), flush=True)


def run(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        handlers=[RotatingFileHandler(log_dir / "sidecar.log", maxBytes=1_000_000, backupCount=3)],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    def launcher_key() -> str:
        key = sys.stdin.readline(256).strip()
        if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError("Invalid launcher secret.")
        return key

    desktop_secret = launcher_key()
    path_key = bytes.fromhex(launcher_key())
    backup = DesktopBackup(root)
    restoring = backup.prepare_startup()
    try:
        _serve(root, desktop_secret, path_key, backup if restoring else None)
    finally:
        if restoring and (root / "restore-request.json").exists():
            backup.rollback_restore()


def _serve(root: Path, desktop_secret: str, path_key: bytes, restore: DesktopBackup | None) -> None:
    from personal_ai_life_os.main import create_app

    database = root / "data" / "lifeos.db"
    database.parent.mkdir(exist_ok=True)
    assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    config = DesktopSettings(
        app_env="desktop",
        data_dir=root,
        database_url=f"sqlite+pysqlite:///{database.as_posix()}",
        auto_create_schema=False,
        registration_mode="closed",
        access_token_secret=secrets.token_urlsafe(48),
        cors_origins="http://tauri.localhost,https://tauri.localhost,tauri://localhost",
        processing_mode="worker",
    )
    migrate(root, database, config, assets)
    bundled_ocr = assets / "tesseract" / "tesseract.exe"
    if bundled_ocr.is_file():
        import os

        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = str(bundled_ocr)
        os.environ["TESSDATA_PREFIX"] = str(bundled_ocr.parent / "tessdata")

    app = create_app(config, desktop_secret=desktop_secret, desktop_path_key=path_key)
    server = DesktopServer(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        proxy_headers=False,
        access_log=False,
        log_config=None,
        loop="asyncio",
        http="h11",
        ws="none",
        timeout_graceful_shutdown=4,
    ))
    server.restore = restore

    def shutdown_on_launcher_exit() -> None:
        # Closing stdin also stops the service if the shell crashes.
        sys.stdin.read(1)
        server.should_exit = True

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if sys.platform == "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        Thread(target=shutdown_on_launcher_exit, daemon=True).start()
        server.run(sockets=[listener])


def main() -> None:
    try:
        if len(sys.argv) != 2:
            raise ValueError("Expected a desktop data directory.")
        root = Path(sys.argv[1])
        if not root.is_absolute():
            raise ValueError("Expected an absolute desktop data directory.")
        run(root)
    except Exception as error:  # noqa: BLE001 - report startup type without including paths or secrets.
        logger.error("Sidecar startup failed (%s).", type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
