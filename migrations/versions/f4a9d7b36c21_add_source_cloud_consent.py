"""add source cloud consent

Revision ID: f4a9d7b36c21
Revises: d2f5a8c14e73
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a9d7b36c21"
down_revision: str | None = "d2f5a8c14e73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_connections",
        sa.Column("cloud_consent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_connections",
        sa.Column("cloud_consent_version", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_connections", "cloud_consent_version")
    op.drop_column("source_connections", "cloud_consent_at")
