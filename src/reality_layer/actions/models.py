from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionType(StrEnum):
    cancel_order = "cancel_order"
    hold_order = "hold_order"
    update_shipping_address = "update_shipping_address"


class ActionStatus(StrEnum):
    proposed = "proposed"
    approval_required = "approval_required"
    approved = "approved"
    rejected = "rejected"
    denied = "denied"
    precondition_failed = "precondition_failed"
    provider_accepted = "provider_accepted"
    verification_pending = "verification_pending"
    verified = "verified"
    verification_failed = "verification_failed"
    state_diverged = "state_diverged"


class ExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    status: ActionStatus
    provider: str
    provider_request_id: str
    idempotency_key: str


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    target_entity: str = Field(pattern=r"^order:[^:]+$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=255)
    expected_state_version: int = Field(ge=1)
    expected_attributes: dict[str, Any] = Field(default_factory=dict)


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    status: ActionStatus
    reason: str
    matched_rule: str | None = None
    policy_version: str
    required_role: str | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class ActionEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    tenant_id: str
    action_id: str
    event_type: str
    actor_role: str
    payload: dict[str, Any]
    previous_event_hash: str | None = None
    event_hash: str


class ActionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ActionDecision
    events: list[ActionEventRecord]


class ActorIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    reason: str | None = None
    event_id: str
    event_hash: str


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ActionStatus
    matched_rule: str | None = None
    reason: str
    policy_version: str
    required_role: str | None = None


class ProviderEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_request_id: str
    request_fingerprint: str
    idempotency_key: str
    accepted_status: str


class VerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: ActionStatus
    reason: str
    observed_status: str | None = None
    attempts: int
    verification_commit_id: str | None = None


class ProjectionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_id: str | None = None
    commit_hash: str | None = None
    previous_hash: str | None = None
    before: dict[str, Any]
    after: dict[str, Any]
    semantic_diff: dict[str, Any]


class HashChainLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    previous_event_hash: str | None = None
    event_hash: str


class ProofBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    tenant_id: str
    status: ActionStatus
    assurance_level: str
    proposal: ActionProposal
    proposer: ActorIdentity | None = None
    approver: ActorIdentity | None = None
    policy: PolicyEvidence | None = None
    idempotency_key: str
    provider: ProviderEvidence | None = None
    verification: VerificationEvidence | None = None
    projection: ProjectionDelta | None = None
    hash_chain: list[HashChainLink] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    events: list[ActionEventRecord]
    verification_commit_id: str | None = None
