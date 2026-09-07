from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reality_layer.db.base import Base

JsonArray = list[Any]
JsonObject = dict[str, Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


class ActionStatus(StrEnum):
    proposed = "proposed"
    approval_required = "approval_required"
    approved = "approved"
    executing = "executing"
    verified = "verified"
    partial = "partial"
    failed = "failed"
    denied = "denied"


class ApprovalState(StrEnum):
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    superseded = "superseded"


class TenantMixin:
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class ObservationLog(TenantMixin, Base):
    __tablename__ = "observation_log"

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    connector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    payload_hash: Mapped[str] = mapped_column(String(95), nullable=False)
    payload_ref: Mapped[str] = mapped_column(Text, nullable=False)
    schema_hint: Mapped[str | None] = mapped_column(String(255))


class ClaimStore(TenantMixin, Base):
    __tablename__ = "claim_store"

    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    attribute: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    source_refs: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflict_status: Mapped[str] = mapped_column(String(64), nullable=False, default="none")
    schema_version: Mapped[str] = mapped_column(String(255), nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_claim_store_entity_attribute", "tenant_id", "entity_id", "attribute"),
    )


class Entity(TenantMixin, Base):
    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_keys: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("tenant_id", "entity_id", name="uq_entities_tenant_entity"),)


class Relation(TenantMixin, Base):
    __tablename__ = "relations"

    relation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_entity: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    to_entity: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StateProjection(TenantMixin, Base):
    __tablename__ = "state_projection"

    entity_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    attributes: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    freshness: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    permissions: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    state_version: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_id", name="uq_state_projection_tenant_entity"),
    )


class CommitLog(TenantMixin, Base):
    __tablename__ = "commit_log"

    commit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_ids: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    author: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    cause: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    action_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    resulting_state_hash: Mapped[str] = mapped_column(String(95), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(95))
    schema_version: Mapped[str] = mapped_column(String(255), nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ActionLedger(TenantMixin, Base):
    __tablename__ = "action_ledger"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entities: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(95), nullable=False)
    preconditions: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    risk_score: Mapped[float] = mapped_column(nullable=False)
    cost_estimate: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    policy_decision: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    approval_ref: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    execution: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    proof_ref: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_ledger_idempotency"),
    )


class Approval(TenantMixin, Base):
    __tablename__ = "approvals"

    approval_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("action_ledger.action_id"), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    rationale: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Outbox(TenantMixin, Base):
    __tablename__ = "outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
