"""SQLAlchemy engine and request-scoped session helpers."""

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from personal_ai_life_os.config import Settings


class Base(DeclarativeBase):
    """Base class for persisted entities."""


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC instants and restore timezone information on SQLite reads."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def create_database_engine(config: Settings) -> Engine:
    """Create an engine and prepare the parent directory for file-backed SQLite."""
    connect_args: dict[str, object] = {}
    if config.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if config.database_url.startswith("sqlite+pysqlite:///./"):
            Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            config.database_url,
            connect_args=connect_args,
            future=True,
        )

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            if config.app_env == "desktop":
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine

    return create_engine(config.database_url, pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Generator[Session, None, None]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
