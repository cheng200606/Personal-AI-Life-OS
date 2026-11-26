"""Add the review inbox for desktop analysis."""

import sqlalchemy as sa
from alembic import op

revision = "c8d73b1e0afd"
down_revision = "b68cce9036fd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("source_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "ordinal", name="uq_desktop_draft_job_ordinal"),
    )
    op.create_index("ix_desktop_drafts_item_id", "desktop_drafts", ["item_id"])
    op.create_index("ix_desktop_drafts_owner_status", "desktop_drafts", ["owner_id", "status"])


def downgrade() -> None:
    op.drop_table("desktop_drafts")
