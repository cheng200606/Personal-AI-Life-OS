"""add search indexes, saved searches, tags, and collections

Revision ID: f9a1c4d8e702
Revises: e8c4f2a7b913
Create Date: 2026-11-26 00:52:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "f9a1c4d8e702"
down_revision: str | None = "e8c4f2a7b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQLITE_INDEX_DDL = (
    "CREATE VIRTUAL TABLE timeline_fts USING fts5(item_id UNINDEXED, title, content, tokenize='trigram')",
    "CREATE VIRTUAL TABLE review_fts USING fts5(record_id UNINDEXED, content, tokenize='trigram')",
    "CREATE VIRTUAL TABLE reminder_fts USING fts5(record_id UNINDEXED, title, content, tokenize='trigram')",
    """
    CREATE TRIGGER timeline_fts_ai AFTER INSERT ON source_items BEGIN
      INSERT INTO timeline_fts(item_id, title, content) VALUES (new.id, new.title, new.content_text);
    END
    """,
    """
    CREATE TRIGGER timeline_fts_au AFTER UPDATE OF title, content_text ON source_items BEGIN
      DELETE FROM timeline_fts WHERE item_id = old.id;
      INSERT INTO timeline_fts(item_id, title, content) VALUES (new.id, new.title, new.content_text);
    END
    """,
    """
    CREATE TRIGGER timeline_fts_ad AFTER DELETE ON source_items BEGIN
      DELETE FROM timeline_fts WHERE item_id = old.id;
    END
    """,
    """
    CREATE TRIGGER review_fts_ai AFTER INSERT ON reviews BEGIN
      INSERT INTO review_fts(record_id, content)
      SELECT new.id, new.final_text WHERE new.status <> 'invalidated' AND new.final_text IS NOT NULL;
    END
    """,
    """
    CREATE TRIGGER review_fts_au AFTER UPDATE OF final_text, status ON reviews BEGIN
      DELETE FROM review_fts WHERE record_id = old.id;
      INSERT INTO review_fts(record_id, content)
      SELECT new.id, new.final_text WHERE new.status <> 'invalidated' AND new.final_text IS NOT NULL;
    END
    """,
    """
    CREATE TRIGGER review_fts_ad AFTER DELETE ON reviews BEGIN
      DELETE FROM review_fts WHERE record_id = old.id;
    END
    """,
    """
    CREATE TRIGGER reminder_fts_ai AFTER INSERT ON reminders BEGIN
      INSERT INTO reminder_fts(record_id, title, content) VALUES (new.id, new.title, coalesce(new.notes, ''));
    END
    """,
    """
    CREATE TRIGGER reminder_fts_au AFTER UPDATE OF title, notes ON reminders BEGIN
      DELETE FROM reminder_fts WHERE record_id = old.id;
      INSERT INTO reminder_fts(record_id, title, content) VALUES (new.id, new.title, coalesce(new.notes, ''));
    END
    """,
    """
    CREATE TRIGGER reminder_fts_ad AFTER DELETE ON reminders BEGIN
      DELETE FROM reminder_fts WHERE record_id = old.id;
    END
    """,
)


def _create_organization_tables() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name_key", name="uq_tag_owner_name"),
    )
    op.create_index("ix_tags_owner_id", "tags", ["owner_id"])
    op.create_index("ix_tags_owner_name", "tags", ["owner_id", "name_key"])
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name_key", name="uq_collection_owner_name"),
    )
    op.create_index("ix_collections_owner_id", "collections", ["owner_id"])
    op.create_index("ix_collections_owner_name", "collections", ["owner_id", "name_key"])
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("tag_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["source_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "tag_id"),
    )
    op.create_index("ix_item_tags_tag_item", "item_tags", ["tag_id", "item_id"])
    op.create_table(
        "item_collections",
        sa.Column("item_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["source_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "collection_id"),
    )
    op.create_index("ix_item_collections_collection_item", "item_collections", ["collection_id", "item_id"])
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name_key", name="uq_saved_search_owner_name"),
    )
    op.create_index("ix_saved_searches_owner_id", "saved_searches", ["owner_id"])
    op.create_index("ix_saved_searches_owner_created", "saved_searches", ["owner_id", "created_at"])


def _create_sqlite_indexes() -> None:
    try:
        for statement in SQLITE_INDEX_DDL:
            op.execute(statement)
    except OperationalError:
        return
    op.execute(
        "INSERT INTO timeline_fts(item_id, title, content) "
        "SELECT id, title, content_text FROM source_items WHERE is_current = 1 AND deleted_at IS NULL"
    )
    op.execute(
        "INSERT INTO review_fts(record_id, content) "
        "SELECT id, final_text FROM reviews WHERE status <> 'invalidated' AND final_text IS NOT NULL"
    )
    op.execute(
        "INSERT INTO reminder_fts(record_id, title, content) "
        "SELECT id, title, coalesce(notes, '') FROM reminders"
    )


def _create_postgres_indexes() -> None:
    op.execute(
        "DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS pg_trgm; "
        "EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;"
    )
    installed = op.get_bind().scalar(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
    if not installed:
        return
    op.create_index(
        "ix_items_title_trgm", "source_items", [sa.text("lower(title) gin_trgm_ops")], postgresql_using="gin"
    )
    op.create_index(
        "ix_items_content_trgm", "source_items", [sa.text("lower(content_text) gin_trgm_ops")], postgresql_using="gin"
    )
    op.create_index(
        "ix_reviews_final_text_trgm", "reviews", [sa.text("lower(final_text) gin_trgm_ops")], postgresql_using="gin"
    )
    op.create_index(
        "ix_reminders_title_trgm", "reminders", [sa.text("lower(title) gin_trgm_ops")], postgresql_using="gin"
    )
    op.create_index(
        "ix_reminders_notes_trgm", "reminders", [sa.text("lower(coalesce(notes, '')) gin_trgm_ops")], postgresql_using="gin"
    )


def upgrade() -> None:
    _create_organization_tables()
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _create_sqlite_indexes()
    elif dialect == "postgresql":
        _create_postgres_indexes()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for trigger in ("timeline_fts_ai", "timeline_fts_au", "timeline_fts_ad", "review_fts_ai", "review_fts_au", "review_fts_ad", "reminder_fts_ai", "reminder_fts_au", "reminder_fts_ad"):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        for table in ("timeline_fts", "review_fts", "reminder_fts"):
            op.execute(f"DROP TABLE IF EXISTS {table}")
    elif dialect == "postgresql":
        for index in ("ix_items_title_trgm", "ix_items_content_trgm", "ix_reviews_final_text_trgm", "ix_reminders_title_trgm", "ix_reminders_notes_trgm"):
            op.execute(f"DROP INDEX IF EXISTS {index}")
    op.drop_table("saved_searches")
    op.drop_table("item_collections")
    op.drop_table("item_tags")
    op.drop_table("collections")
    op.drop_table("tags")
