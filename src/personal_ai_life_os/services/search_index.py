"""Search candidate indexes with authoritative row filtering at query time."""

import logging

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SQLITE_INDEX_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS timeline_fts USING fts5(item_id UNINDEXED, title, content, tokenize='trigram')",
    "CREATE VIRTUAL TABLE IF NOT EXISTS review_fts USING fts5(record_id UNINDEXED, content, tokenize='trigram')",
    "CREATE VIRTUAL TABLE IF NOT EXISTS reminder_fts USING fts5(record_id UNINDEXED, title, content, tokenize='trigram')",
    """
    CREATE TRIGGER IF NOT EXISTS timeline_fts_ai AFTER INSERT ON source_items BEGIN
      INSERT INTO timeline_fts(item_id, title, content) VALUES (new.id, new.title, new.content_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS timeline_fts_au AFTER UPDATE OF title, content_text ON source_items BEGIN
      DELETE FROM timeline_fts WHERE item_id = old.id;
      INSERT INTO timeline_fts(item_id, title, content) VALUES (new.id, new.title, new.content_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS timeline_fts_ad AFTER DELETE ON source_items BEGIN
      DELETE FROM timeline_fts WHERE item_id = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS review_fts_ai AFTER INSERT ON reviews BEGIN
      INSERT INTO review_fts(record_id, content)
      SELECT new.id, new.final_text WHERE new.status <> 'invalidated' AND new.final_text IS NOT NULL;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS review_fts_au AFTER UPDATE OF final_text, status ON reviews BEGIN
      DELETE FROM review_fts WHERE record_id = old.id;
      INSERT INTO review_fts(record_id, content)
      SELECT new.id, new.final_text WHERE new.status <> 'invalidated' AND new.final_text IS NOT NULL;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS review_fts_ad AFTER DELETE ON reviews BEGIN
      DELETE FROM review_fts WHERE record_id = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS reminder_fts_ai AFTER INSERT ON reminders BEGIN
      INSERT INTO reminder_fts(record_id, title, content) VALUES (new.id, new.title, coalesce(new.notes, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS reminder_fts_au AFTER UPDATE OF title, notes ON reminders BEGIN
      DELETE FROM reminder_fts WHERE record_id = old.id;
      INSERT INTO reminder_fts(record_id, title, content) VALUES (new.id, new.title, coalesce(new.notes, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS reminder_fts_ad AFTER DELETE ON reminders BEGIN
      DELETE FROM reminder_fts WHERE record_id = old.id;
    END
    """,
)


def ensure_sqlite_search_index(session: Session) -> bool:
    if session.get_bind().dialect.name != "sqlite":
        return False
    try:
        for statement in SQLITE_INDEX_DDL:
            session.execute(text(statement))
        session.commit()
        return True
    except OperationalError as error:
        session.rollback()
        logger.info("SQLite FTS5 trigram unavailable; using LIKE search: %s", error)
        return False


def ensure_postgres_search_indexes(session: Session) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return False
    try:
        session.execute(
            text(
                "DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS pg_trgm; "
                "EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;"
            )
        )
        installed = session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
        if installed:
            for statement in (
                "CREATE INDEX IF NOT EXISTS ix_items_title_trgm ON source_items USING gin (lower(title) gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS ix_items_content_trgm ON source_items USING gin (lower(content_text) gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS ix_reviews_final_text_trgm ON reviews USING gin (lower(final_text) gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS ix_reminders_title_trgm ON reminders USING gin (lower(title) gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS ix_reminders_notes_trgm ON reminders USING gin (lower(coalesce(notes, '')) gin_trgm_ops)",
            ):
                session.execute(text(statement))
        session.commit()
        return bool(installed)
    except SQLAlchemyError as error:
        session.rollback()
        logger.info("PostgreSQL pg_trgm unavailable; using LIKE search: %s", error)
        return False


def rebuild_search_index(session: Session) -> str:
    if session.get_bind().dialect.name == "postgresql":
        ensure_postgres_search_indexes(session)
        return search_backend(session)
    if session.get_bind().dialect.name != "sqlite":
        return search_backend(session)
    if not ensure_sqlite_search_index(session):
        return "like"
    session.execute(text("DELETE FROM timeline_fts"))
    session.execute(text("DELETE FROM review_fts"))
    session.execute(text("DELETE FROM reminder_fts"))
    session.execute(
        text(
            "INSERT INTO timeline_fts(item_id, title, content) "
            "SELECT id, title, content_text FROM source_items "
            "WHERE is_current = 1 AND deleted_at IS NULL"
        )
    )
    session.execute(
        text(
            "INSERT INTO review_fts(record_id, content) "
            "SELECT id, final_text FROM reviews "
            "WHERE status <> 'invalidated' AND final_text IS NOT NULL"
        )
    )
    session.execute(
        text(
            "INSERT INTO reminder_fts(record_id, title, content) "
            "SELECT id, title, coalesce(notes, '') FROM reminders"
        )
    )
    session.commit()
    return "sqlite-fts5-trigram"


def search_backend(session: Session) -> str:
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        exists = session.scalar(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'timeline_fts'")
        )
        return "sqlite-fts5-trigram" if exists else "like"
    if dialect == "postgresql":
        exists = session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
        return "postgresql-pg_trgm" if exists else "like"
    return "like"


def fts_candidate_filter(session: Session, table: str, id_column, query: str, record_column: str = "item_id"):
    if search_backend(session) != "sqlite-fts5-trigram" or len(query) < 3:
        return None
    statement = text(f"SELECT {record_column} FROM {table} WHERE {table} MATCH :query")
    return id_column.in_(statement.bindparams(query='"' + query.replace('"', '""') + '"'))
