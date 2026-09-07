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
    verified = "verified"
    verification_failed = "verification_failed"


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


class ProofBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    tenant_id: str
    status: ActionStatus
    assurance_level: str
    proposal: ActionProposal
    events: list[ActionEventRecord]
    verification_commit_id: str | None = None
