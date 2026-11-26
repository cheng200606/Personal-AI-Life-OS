"""add per-provider consent and review version snapshots

Revision ID: a1b7c9d3e504
Revises: f9a1c4d8e702
Create Date: 2026-11-26 02:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b7c9d3e504"
down_revision: str | None = "f9a1c4d8e702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_consents",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("disclosure_version", sa.String(length=120), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "provider_id", name="uq_model_consent_owner_provider"),
    )
    op.create_index("ix_model_consents_owner_id", "model_consents", ["owner_id"])
    op.create_index(
        "ix_model_consents_owner_provider", "model_consents", ["owner_id", "provider_id"]
    )
    op.create_table(
        "review_versions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("review_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "version_number", name="uq_review_version_number"),
    )
    op.create_index("ix_review_versions_review_id", "review_versions", ["review_id"])
    op.create_index(
        "ix_review_versions_review_created", "review_versions", ["review_id", "created_at"]
    )
    op.add_column(
        "review_schedules",
        sa.Column("provider_id", sa.String(length=80), nullable=False, server_default="default"),
    )
    op.add_column("review_schedules", sa.Column("model", sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column("review_schedules", "model")
    op.drop_column("review_schedules", "provider_id")
    op.drop_table("review_versions")
    op.drop_table("model_consents")
