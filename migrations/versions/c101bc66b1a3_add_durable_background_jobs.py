"""add durable background jobs

Revision ID: c101bc66b1a3
Revises: eb3ff930ec06
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c101bc66b1a3"
down_revision: str | None = "eb3ff930ec06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("source_item_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("sync_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("review_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "dedupe_key", name="uq_background_job_owner_dedupe"),
    )
    op.create_index("ix_background_jobs_owner_id", "background_jobs", ["owner_id"])
    op.create_index("ix_background_jobs_kind", "background_jobs", ["kind"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_available_at", "background_jobs", ["available_at"])
    op.create_index(
        "ix_background_jobs_status_available", "background_jobs", ["status", "available_at"]
    )
    op.create_index("ix_background_jobs_owner_created", "background_jobs", ["owner_id", "created_at"])
    op.create_index("ix_background_jobs_source_id", "background_jobs", ["source_id"])
    op.create_index("ix_background_jobs_source_item_id", "background_jobs", ["source_item_id"])
    op.create_index("ix_background_jobs_sync_run_id", "background_jobs", ["sync_run_id"])
    op.create_index("ix_background_jobs_review_id", "background_jobs", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_review_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_sync_run_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_source_item_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_source_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_owner_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status_available", table_name="background_jobs")
    op.drop_index("ix_background_jobs_available_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_kind", table_name="background_jobs")
    op.drop_index("ix_background_jobs_owner_id", table_name="background_jobs")
    op.drop_table("background_jobs")
