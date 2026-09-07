"""foundation schema

Revision ID: 20260906_0001
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260906_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "observation_log",
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("connector_version", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=95), nullable=False),
        sa.Column("payload_ref", sa.Text(), nullable=False),
        sa.Column("schema_hint", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("observation_id"),
    )
    op.create_index("ix_observation_log_source_id", "observation_log", ["source_id"])
    op.create_index("ix_observation_log_tenant_id", "observation_log", ["tenant_id"])

    op.create_table(
        "claim_store",
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("attribute", sa.String(length=255), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conflict_status", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=255), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("claim_id"),
    )
    op.create_index(
        "ix_claim_store_entity_attribute",
        "claim_store",
        ["tenant_id", "entity_id", "attribute"],
    )
    op.create_index("ix_claim_store_entity_id", "claim_store", ["entity_id"])
    op.create_index("ix_claim_store_tenant_id", "claim_store", ["tenant_id"])

    op.create_table(
        "entities",
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("canonical_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("tenant_id", "entity_id", name="uq_entities_tenant_entity"),
    )
    op.create_index("ix_entities_tenant_id", "entities", ["tenant_id"])
    op.create_index("ix_entities_type", "entities", ["type"])

    op.create_table(
        "relations",
        sa.Column("relation_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("from_entity", sa.String(length=255), nullable=False),
        sa.Column("to_entity", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("relation_id"),
    )
    op.create_index("ix_relations_from_entity", "relations", ["from_entity"])
    op.create_index("ix_relations_tenant_id", "relations", ["tenant_id"])
    op.create_index("ix_relations_to_entity", "relations", ["to_entity"])

    op.create_table(
        "state_projection",
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("freshness", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conflicts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("entity_id"),
        sa.UniqueConstraint("tenant_id", "entity_id", name="uq_state_projection_tenant_entity"),
    )
    op.create_index("ix_state_projection_tenant_id", "state_projection", ["tenant_id"])

    op.create_table(
        "commit_log",
        sa.Column("commit_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("parent_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("author", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cause", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action_ref", sa.String(length=64), nullable=True),
        sa.Column("resulting_state_hash", sa.String(length=95), nullable=False),
        sa.Column("prev_hash", sa.String(length=95), nullable=True),
        sa.Column("schema_version", sa.String(length=255), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("commit_id"),
    )
    op.create_index("ix_commit_log_action_ref", "commit_log", ["action_ref"])
    op.create_index("ix_commit_log_tenant_id", "commit_log", ["tenant_id"])

    op.create_table(
        "action_ledger",
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("proposed_by", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("target_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters_hash", sa.String(length=95), nullable=False),
        sa.Column("preconditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("cost_estimate", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approval_ref", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("execution", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proof_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("action_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_ledger_idempotency"),
    )
    op.create_index("ix_action_ledger_tenant_id", "action_ledger", ["tenant_id"])

    op.create_table(
        "approvals",
        sa.Column("approval_ref", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("reviewer", sa.String(length=255), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["action_id"], ["action_ledger.action_id"]),
        sa.PrimaryKeyConstraint("approval_ref"),
    )
    op.create_index("ix_approvals_tenant_id", "approvals", ["tenant_id"])

    op.create_table(
        "outbox",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_outbox_event_type", "outbox", ["event_type"])
    op.create_index("ix_outbox_tenant_id", "outbox", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_tenant_id", table_name="outbox")
    op.drop_index("ix_outbox_event_type", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("ix_approvals_tenant_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_action_ledger_tenant_id", table_name="action_ledger")
    op.drop_table("action_ledger")
    op.drop_index("ix_commit_log_tenant_id", table_name="commit_log")
    op.drop_index("ix_commit_log_action_ref", table_name="commit_log")
    op.drop_table("commit_log")
    op.drop_index("ix_state_projection_tenant_id", table_name="state_projection")
    op.drop_table("state_projection")
    op.drop_index("ix_relations_to_entity", table_name="relations")
    op.drop_index("ix_relations_tenant_id", table_name="relations")
    op.drop_index("ix_relations_from_entity", table_name="relations")
    op.drop_table("relations")
    op.drop_index("ix_entities_type", table_name="entities")
    op.drop_index("ix_entities_tenant_id", table_name="entities")
    op.drop_table("entities")
    op.drop_index("ix_claim_store_tenant_id", table_name="claim_store")
    op.drop_index("ix_claim_store_entity_id", table_name="claim_store")
    op.drop_index("ix_claim_store_entity_attribute", table_name="claim_store")
    op.drop_table("claim_store")
    op.drop_index("ix_observation_log_tenant_id", table_name="observation_log")
    op.drop_index("ix_observation_log_source_id", table_name="observation_log")
    op.drop_table("observation_log")
