"""align investor mvp schema

Revision ID: 20260907_0002
Revises: 20260906_0001
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260907_0002"
down_revision: str | None = "20260906_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = (
    "observation_log",
    "commit_log",
    "action_event",
    "policy_version",
)


def _install_append_only_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table % cannot be updated or deleted', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER prevent_{table_name}_mutation
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation()
            """
        )


def _drop_append_only_triggers() -> None:
    for table_name in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS prevent_{table_name}_mutation ON {table_name};")
    op.execute("DROP FUNCTION IF EXISTS prevent_append_only_mutation();")


def upgrade() -> None:
    op.drop_table("approvals")
    op.drop_table("action_ledger")
    op.drop_table("outbox")
    op.drop_table("commit_log")
    op.drop_table("state_projection")
    op.drop_table("relations")
    op.drop_table("entities")
    op.drop_table("claim_store")
    op.drop_table("observation_log")

    op.create_table(
        "workspace",
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bounded_backfill", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.UniqueConstraint("tenant_id", "workspace_id", name="uq_workspace_tenant"),
    )
    op.create_index("ix_workspace_tenant_id", "workspace", ["tenant_id"])

    op.create_table(
        "connector",
        sa.Column("connector_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_ref", sa.String(length=255), nullable=True),
        sa.Column("last_check", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("connector_id"),
        sa.UniqueConstraint("tenant_id", "connector_id", name="uq_connector_tenant"),
    )
    op.create_index("ix_connector_tenant_id", "connector", ["tenant_id"])
    op.create_index("ix_connector_workspace_id", "connector", ["workspace_id"])

    op.create_table(
        "observation_log",
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("connector_id", sa.String(length=64), nullable=False),
        sa.Column("external_object_type", sa.String(length=64), nullable=False),
        sa.Column("external_object_id", sa.String(length=255), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=95), nullable=False),
        sa.Column("payload_ref", sa.Text(), nullable=False),
        sa.Column("connector_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("ingest_outcome", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "observation_id", name="pk_observation_log"),
        sa.UniqueConstraint(
            "tenant_id",
            "connector_id",
            "external_event_id",
            name="uq_observation_external_event",
        ),
    )
    op.create_index("ix_observation_log_connector_id", "observation_log", ["connector_id"])
    op.create_index("ix_observation_log_correlation_id", "observation_log", ["correlation_id"])
    op.create_index(
        "ix_observation_external_object",
        "observation_log",
        ["tenant_id", "connector_id", "external_object_type", "external_object_id"],
    )
    op.create_index("ix_observation_log_tenant_id", "observation_log", ["tenant_id"])

    op.create_table(
        "state_projection",
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("freshness", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("producing_commit_id", sa.String(length=64), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "entity_id", name="pk_state_projection"),
        sa.UniqueConstraint("tenant_id", "entity_id", name="uq_state_projection_tenant_entity"),
    )
    op.create_index("ix_state_projection_entity_type", "state_projection", ["entity_type"])
    op.create_index(
        "ix_state_projection_producing_commit_id",
        "state_projection",
        ["producing_commit_id"],
    )
    op.create_index("ix_state_projection_tenant_id", "state_projection", ["tenant_id"])

    op.create_table(
        "commit_log",
        sa.Column("commit_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("parent_commit_id", sa.String(length=64), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("actor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cause", sa.String(length=64), nullable=False),
        sa.Column("observation_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=True),
        sa.Column("mapping_version", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("semantic_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assurance_level", sa.String(length=64), nullable=False),
        sa.Column("previous_hash", sa.String(length=95), nullable=True),
        sa.Column("hash", sa.String(length=95), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("commit_id"),
    )
    op.create_index("ix_commit_log_action_id", "commit_log", ["action_id"])
    op.create_index("ix_commit_log_entity_id", "commit_log", ["entity_id"])
    op.create_index("ix_commit_log_parent_commit_id", "commit_log", ["parent_commit_id"])
    op.create_index("ix_commit_log_tenant_id", "commit_log", ["tenant_id"])

    op.create_table(
        "action_event",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=255), nullable=False),
        sa.Column("actor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("previous_event_hash", sa.String(length=95), nullable=True),
        sa.Column("event_hash", sa.String(length=95), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", name="pk_action_event"),
        sa.UniqueConstraint("tenant_id", "event_hash", name="uq_action_event_hash_tenant"),
    )
    op.create_index("ix_action_event_action_id", "action_event", ["action_id"])
    op.create_index("ix_action_event_correlation_id", "action_event", ["correlation_id"])
    op.create_index("ix_action_event_tenant_id", "action_event", ["tenant_id"])

    op.create_table(
        "policy_version",
        sa.Column("policy_version_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("document_hash", sa.String(length=95), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("policy_version_id"),
        sa.UniqueConstraint("tenant_id", "workspace_id", "version", name="uq_policy_version"),
    )
    op.create_index("ix_policy_version_tenant_id", "policy_version", ["tenant_id"])
    op.create_index("ix_policy_version_workspace_id", "policy_version", ["workspace_id"])

    _install_append_only_triggers()


def downgrade() -> None:
    _drop_append_only_triggers()
    op.drop_table("policy_version")
    op.drop_table("action_event")
    op.drop_table("commit_log")
    op.drop_table("state_projection")
    op.drop_table("observation_log")
    op.drop_table("connector")
    op.drop_table("workspace")
