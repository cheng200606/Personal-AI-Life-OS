"""add evidence graph tables

Revision ID: d2f5a8c14e73
Revises: b7d4f6a1c902
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f5a8c14e73"
down_revision: str | None = "b7d4f6a1c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_entities",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("merged_into_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["graph_entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_entities_owner_id", "graph_entities", ["owner_id"])
    op.create_index("ix_graph_entities_entity_type", "graph_entities", ["entity_type"])
    op.create_index("ix_graph_entities_normalized_name", "graph_entities", ["normalized_name"])
    op.create_index("ix_graph_entities_status", "graph_entities", ["status"])
    op.create_index(
        "ix_graph_entities_owner_type", "graph_entities", ["owner_id", "entity_type"]
    )
    op.create_index(
        "ix_graph_entities_owner_name", "graph_entities", ["owner_id", "normalized_name"]
    )

    op.create_table(
        "graph_relations",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("from_entity_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("to_entity_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_relations_owner_id", "graph_relations", ["owner_id"])
    op.create_index("ix_graph_relations_relation_type", "graph_relations", ["relation_type"])
    op.create_index("ix_graph_relations_status", "graph_relations", ["status"])
    op.create_index(
        "ix_graph_relations_owner_type", "graph_relations", ["owner_id", "relation_type"]
    )
    op.create_index("ix_graph_relations_from", "graph_relations", ["from_entity_id"])
    op.create_index("ix_graph_relations_to", "graph_relations", ["to_entity_id"])

    op.create_table(
        "graph_evidence",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("relation_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("source_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("source_item_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("availability", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_id IS NOT NULL OR relation_id IS NOT NULL",
            name="ck_graph_evidence_target",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["relation_id"], ["graph_relations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_evidence_owner_id", "graph_evidence", ["owner_id"])
    op.create_index("ix_graph_evidence_availability", "graph_evidence", ["availability"])
    op.create_index(
        "ix_graph_evidence_owner_source", "graph_evidence", ["owner_id", "source_id"]
    )
    op.create_index(
        "ix_graph_evidence_owner_available", "graph_evidence", ["owner_id", "availability"]
    )

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("normalized_alias", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_aliases_owner_id", "entity_aliases", ["owner_id"])
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.create_index("ix_entity_aliases_normalized_alias", "entity_aliases", ["normalized_alias"])
    op.create_index(
        "ix_entity_aliases_owner_name", "entity_aliases", ["owner_id", "normalized_alias"]
    )

    op.create_table(
        "entity_merge_logs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("target_entity_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_entity_id"], ["graph_entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["graph_entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_merge_logs_owner_id", "entity_merge_logs", ["owner_id"])
    op.create_index(
        "ix_entity_merge_logs_owner_created", "entity_merge_logs", ["owner_id", "created_at"]
    )

    op.create_table(
        "ontology_types",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "kind", "name", name="uq_ontology_type_owner_kind_name"),
    )
    op.create_index("ix_ontology_types_owner_id", "ontology_types", ["owner_id"])
    op.create_index("ix_ontology_types_status", "ontology_types", ["status"])
    op.create_index(
        "ix_ontology_types_owner_status", "ontology_types", ["owner_id", "status"]
    )

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("requested_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_item_ids", sa.JSON(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("entity_count", sa.Integer(), nullable=False),
        sa.Column("relation_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_extraction_runs_owner_id", "extraction_runs", ["owner_id"])
    op.create_index("ix_extraction_runs_status", "extraction_runs", ["status"])
    op.create_index("ix_extraction_runs_requested_hash", "extraction_runs", ["requested_hash"])
    op.create_index(
        "ix_extraction_runs_owner_created", "extraction_runs", ["owner_id", "created_at"]
    )

    op.create_table(
        "graph_review_items",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_review_items_owner_id", "graph_review_items", ["owner_id"])
    op.create_index("ix_graph_review_items_status", "graph_review_items", ["status"])
    op.create_index(
        "ix_graph_review_items_owner_status", "graph_review_items", ["owner_id", "status"]
    )
    op.create_index(
        "ix_graph_review_items_owner_created", "graph_review_items", ["owner_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_graph_review_items_owner_created", table_name="graph_review_items")
    op.drop_index("ix_graph_review_items_owner_status", table_name="graph_review_items")
    op.drop_index("ix_graph_review_items_status", table_name="graph_review_items")
    op.drop_index("ix_graph_review_items_owner_id", table_name="graph_review_items")
    op.drop_table("graph_review_items")

    op.drop_index("ix_extraction_runs_owner_created", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_requested_hash", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_status", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_owner_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")

    op.drop_index("ix_ontology_types_owner_status", table_name="ontology_types")
    op.drop_index("ix_ontology_types_status", table_name="ontology_types")
    op.drop_index("ix_ontology_types_owner_id", table_name="ontology_types")
    op.drop_table("ontology_types")

    op.drop_index("ix_entity_merge_logs_owner_created", table_name="entity_merge_logs")
    op.drop_index("ix_entity_merge_logs_owner_id", table_name="entity_merge_logs")
    op.drop_table("entity_merge_logs")

    op.drop_index("ix_entity_aliases_owner_name", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_normalized_alias", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_entity_id", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_owner_id", table_name="entity_aliases")
    op.drop_table("entity_aliases")

    op.drop_index("ix_graph_evidence_owner_available", table_name="graph_evidence")
    op.drop_index("ix_graph_evidence_owner_source", table_name="graph_evidence")
    op.drop_index("ix_graph_evidence_availability", table_name="graph_evidence")
    op.drop_index("ix_graph_evidence_owner_id", table_name="graph_evidence")
    op.drop_table("graph_evidence")

    op.drop_index("ix_graph_relations_to", table_name="graph_relations")
    op.drop_index("ix_graph_relations_from", table_name="graph_relations")
    op.drop_index("ix_graph_relations_owner_type", table_name="graph_relations")
    op.drop_index("ix_graph_relations_status", table_name="graph_relations")
    op.drop_index("ix_graph_relations_relation_type", table_name="graph_relations")
    op.drop_index("ix_graph_relations_owner_id", table_name="graph_relations")
    op.drop_table("graph_relations")

    op.drop_index("ix_graph_entities_owner_name", table_name="graph_entities")
    op.drop_index("ix_graph_entities_owner_type", table_name="graph_entities")
    op.drop_index("ix_graph_entities_status", table_name="graph_entities")
    op.drop_index("ix_graph_entities_normalized_name", table_name="graph_entities")
    op.drop_index("ix_graph_entities_entity_type", table_name="graph_entities")
    op.drop_index("ix_graph_entities_owner_id", table_name="graph_entities")
    op.drop_table("graph_entities")
