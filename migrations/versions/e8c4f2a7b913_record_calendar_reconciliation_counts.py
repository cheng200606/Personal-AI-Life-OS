"""record calendar snapshot reconciliation counts

Revision ID: e8c4f2a7b913
Revises: d7f1a3b5c902
Create Date: 2026-11-26 00:26:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8c4f2a7b913"
down_revision: str | None = "d7f1a3b5c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sync_runs", sa.Column("items_updated", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("sync_runs", sa.Column("items_removed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("sync_runs", sa.Column("items_skipped", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("sync_runs", "items_skipped")
    op.drop_column("sync_runs", "items_removed")
    op.drop_column("sync_runs", "items_updated")
