"""Persist desktop folder permissions and file synchronization status."""

import sqlalchemy as sa
from alembic import op

revision = "b68cce9036fd"
down_revision = "a1b7c9d3e504"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_folders",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source_connections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("path_key", sa.String(64), unique=True, nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("scan_status", sa.String(24), nullable=False),
        sa.Column("last_scan_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "desktop_folder_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("desktop_folders.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_key", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("conversation_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "file_key", name="uq_desktop_folder_file"),
    )
    op.create_index("ix_desktop_folder_files_source_id", "desktop_folder_files", ["source_id"])


def downgrade() -> None:
    op.drop_table("desktop_folder_files")
    op.drop_table("desktop_folders")
