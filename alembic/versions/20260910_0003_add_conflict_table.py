"""add conflict table

Revision ID: 20260910_0003
Revises: 20260907_0002
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0003"
down_revision: str | None = "20260907_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conflict",
        sa.Column("conflict_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("attribute", sa.String(length=255), nullable=False),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "conflict_id", name="pk_conflict"),
    )
    op.create_index("ix_conflict_tenant_id", "conflict", ["tenant_id"])
    op.create_index("ix_conflict_entity_id", "conflict", ["entity_id"])
    op.create_index("ix_conflict_status", "conflict", ["status"])
    op.create_index(
        "ix_conflict_entity", "conflict", ["tenant_id", "entity_type", "entity_id"]
    )


def downgrade() -> None:
    op.drop_table("conflict")
