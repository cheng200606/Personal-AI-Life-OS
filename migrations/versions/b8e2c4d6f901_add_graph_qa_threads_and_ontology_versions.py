"""add graph question threads and ontology versions

Revision ID: b8e2c4d6f901
Revises: f4a9d7b36c21
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2c4d6f901"
down_revision: str | None = "f4a9d7b36c21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ontology_types",
        sa.Column("created_by", sa.String(length=32), nullable=False, server_default="model"),
    )
    op.add_column(
        "ontology_types",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "qa_threads",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_threads_owner_id", "qa_threads", ["owner_id"])
    op.create_index("ix_qa_threads_owner_updated", "qa_threads", ["owner_id", "updated_at"])

    op.create_table(
        "qa_messages",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("thread_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["qa_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_messages_owner_id", "qa_messages", ["owner_id"])
    op.create_index("ix_qa_messages_thread_id", "qa_messages", ["thread_id"])
    op.create_index(
        "ix_qa_messages_thread_created", "qa_messages", ["thread_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_messages_thread_created", table_name="qa_messages")
    op.drop_index("ix_qa_messages_thread_id", table_name="qa_messages")
    op.drop_index("ix_qa_messages_owner_id", table_name="qa_messages")
    op.drop_table("qa_messages")

    op.drop_index("ix_qa_threads_owner_updated", table_name="qa_threads")
    op.drop_index("ix_qa_threads_owner_id", table_name="qa_threads")
    op.drop_table("qa_threads")

    op.drop_column("ontology_types", "version")
    op.drop_column("ontology_types", "created_by")
