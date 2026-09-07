from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reality_layer.db.base import Base

JsonArray = list[Any]
JsonObject = dict[str, Any]


class WorkspaceMode(StrEnum):
    observe_only = "observe_only"
    demo_proposal = "demo_proposal"


class ConnectorKind(StrEnum):
    shopify = "shopify"
    easypost = "easypost"


class TenantMixin:
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class Workspace(TenantMixin, Base):
    __tablename__ = "workspace"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(
        String(64), nullable=False, default=WorkspaceMode.observe_only
    )
    thresholds: Mapped[JsonObject] = mapped_column(JSONB, nullable=False, default=dict)
    bounded_backfill: Mapped[JsonObject] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("tenant_id", "workspace_id", name="uq_workspace_tenant"),)


class Connector(TenantMixin, Base):
    __tablename__ = "connector"

    connector_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities: Mapped[JsonObject] = mapped_column(JSONB, nullable=False, default=dict)
    required_scopes: Mapped[JsonArray] = mapped_column(JSONB, nullable=False, default=list)
    config_ref: Mapped[str | None] = mapped_column(String(255))
    last_check: Mapped[JsonObject] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_id", name="uq_connector_tenant"),
    )


class ObservationLog(TenantMixin, Base):
    __tablename__ = "observation_log"

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_object_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(255))
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    payload_hash: Mapped[str] = mapped_column(String(95), nullable=False)
    payload_ref: Mapped[str] = mapped_column(Text, nullable=False)
    connector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ingest_outcome: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connector_id",
            "external_event_id",
            name="uq_observation_external_event",
        ),
        Index(
            "ix_observation_external_object",
            "tenant_id",
            "connector_id",
            "external_object_type",
            "external_object_id",
        ),
    )


class StateProjection(TenantMixin, Base):
    __tablename__ = "state_projection"

    entity_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attributes: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    freshness: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    producing_commit_id: Mapped[str | None] = mapped_column(String(64), index=True)
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
    parent_commit_id: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    actor: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    cause: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_ids: Mapped[JsonArray] = mapped_column(JSONB, nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(64), index=True)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    after: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    semantic_diff: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    assurance_level: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(95))
    hash: Mapped[str] = mapped_column(String(95), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ActionEvent(TenantMixin, Base):
    __tablename__ = "action_event"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    evidence_refs: Mapped[JsonArray] = mapped_column(JSONB, nullable=False, default=list)
    previous_event_hash: Mapped[str | None] = mapped_column(String(95))
    event_hash: Mapped[str] = mapped_column(String(95), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "event_hash", name="uq_action_event_hash_tenant"),
    )


class PolicyVersion(TenantMixin, Base):
    __tablename__ = "policy_version"

    policy_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[JsonObject] = mapped_column(JSONB, nullable=False)
    document_hash: Mapped[str] = mapped_column(String(95), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "version", name="uq_policy_version"),
    )
