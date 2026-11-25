"""add weekly review schedules

Revision ID: b7d4f6a1c902
Revises: c101bc66b1a3
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d4f6a1c902"
down_revision: str | None = "c101bc66b1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_schedules",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("local_hour", sa.Integer(), nullable=False),
        sa.Column("local_minute", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("use_external_model", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_review_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_review_id"], ["reviews.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", name="uq_review_schedule_owner"),
    )
    op.create_index(
        "ix_review_schedules_due", "review_schedules", ["enabled", "next_run_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_schedules_due", table_name="review_schedules")
    op.drop_table("review_schedules")
