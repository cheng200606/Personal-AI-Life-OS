"""add insights, agent actions, and plugin manifests

Revision ID: d7f1a3b5c902
Revises: b8e2c4d6f901
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7f1a3b5c902"
down_revision: str | None = "b8e2c4d6f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_dismissals",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("insight_key", sa.String(length=240), nullable=False),
        sa.Column("rule", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "insight_key", name="uq_insight_dismissal_owner_key"),
    )
    op.create_index("ix_insight_dismissals_owner_id", "insight_dismissals", ["owner_id"])
    op.create_index("ix_insight_dismissals_rule", "insight_dismissals", ["rule"])
    op.create_index(
        "ix_insight_dismissals_owner_rule", "insight_dismissals", ["owner_id", "rule"]
    )

    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("approval", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_actions_owner_id", "agent_actions", ["owner_id"])
    op.create_index("ix_agent_actions_kind", "agent_actions", ["kind"])
    op.create_index("ix_agent_actions_status", "agent_actions", ["status"])
    op.create_index(
        "ix_agent_actions_owner_created", "agent_actions", ["owner_id", "created_at"]
    )
    op.create_index(
        "ix_agent_actions_owner_status", "agent_actions", ["owner_id", "status"]
    )

    op.create_table(
        "plugin_manifests",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("entrypoint", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_plugin_manifest_owner_name"),
    )
    op.create_index("ix_plugin_manifests_owner_id", "plugin_manifests", ["owner_id"])
    op.create_index("ix_plugin_manifests_status", "plugin_manifests", ["status"])
    op.create_index(
        "ix_plugin_manifests_owner_status", "plugin_manifests", ["owner_id", "status"]
    )

    op.create_table(
        "plugin_permissions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("plugin_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("permission", sa.String(length=80), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_manifests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_id", "permission", name="uq_plugin_permission"),
    )
    op.create_index("ix_plugin_permissions_owner_id", "plugin_permissions", ["owner_id"])
    op.create_index("ix_plugin_permissions_plugin_id", "plugin_permissions", ["plugin_id"])

    op.create_table(
        "plugin_audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("plugin_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_manifests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plugin_audit_logs_owner_id", "plugin_audit_logs", ["owner_id"])
    op.create_index(
        "ix_plugin_audit_logs_owner_created", "plugin_audit_logs", ["owner_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_plugin_audit_logs_owner_created", table_name="plugin_audit_logs")
    op.drop_index("ix_plugin_audit_logs_owner_id", table_name="plugin_audit_logs")
    op.drop_table("plugin_audit_logs")

    op.drop_index("ix_plugin_permissions_plugin_id", table_name="plugin_permissions")
    op.drop_index("ix_plugin_permissions_owner_id", table_name="plugin_permissions")
    op.drop_table("plugin_permissions")

    op.drop_index("ix_plugin_manifests_owner_status", table_name="plugin_manifests")
    op.drop_index("ix_plugin_manifests_status", table_name="plugin_manifests")
    op.drop_index("ix_plugin_manifests_owner_id", table_name="plugin_manifests")
    op.drop_table("plugin_manifests")

    op.drop_index("ix_agent_actions_owner_status", table_name="agent_actions")
    op.drop_index("ix_agent_actions_owner_created", table_name="agent_actions")
    op.drop_index("ix_agent_actions_status", table_name="agent_actions")
    op.drop_index("ix_agent_actions_kind", table_name="agent_actions")
    op.drop_index("ix_agent_actions_owner_id", table_name="agent_actions")
    op.drop_table("agent_actions")

    op.drop_index("ix_insight_dismissals_owner_rule", table_name="insight_dismissals")
    op.drop_index("ix_insight_dismissals_rule", table_name="insight_dismissals")
    op.drop_index("ix_insight_dismissals_owner_id", table_name="insight_dismissals")
    op.drop_table("insight_dismissals")
