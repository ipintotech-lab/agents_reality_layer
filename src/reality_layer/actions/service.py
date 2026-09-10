from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from reality_layer.actions.models import (
    ActionDecision,
    ActionEventRecord,
    ActionProposal,
    ActionStatus,
    ActorIdentity,
    ApprovalRequest,
    ExecutionReceipt,
    HashChainLink,
    PolicyEvidence,
    ProjectionDelta,
    ProofBundle,
    ProviderEvidence,
    VerificationEvidence,
)
from reality_layer.actions.policy import evaluate_policy
from reality_layer.reality_git import hash_json
from reality_layer.world_state.models import CommitRecord, OrderState


class CancelOrderExecutor(Protocol):
    def __call__(
        self, action_id: str, order_id: str, idempotency_key: str
    ) -> ExecutionReceipt:
        ...


@dataclass
class StoredAction:
    proposal: ActionProposal
    decision: ActionDecision
    proposer_role: str
    tenant_id: str


class ActionService:
    def __init__(self) -> None:
        self._actions: dict[str, StoredAction] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._events: dict[str, list[ActionEventRecord]] = {}
        self._executions: dict[tuple[str, str], ExecutionReceipt] = {}

    def propose(
        self,
        proposal: ActionProposal,
        role: str,
        tenant_id: str = "demo",
        *,
        workspace_mode: str = "demo_proposal",
        order_value: float | None = None,
        value_limit: float | None = None,
        has_conflict: bool = False,
    ) -> ActionDecision:
        existing_id = self._idempotency.get((tenant_id, proposal.idempotency_key))
        if existing_id is not None:
            return self._actions[existing_id].decision

        action_id = f"act_{uuid4().hex[:16]}"
        decision = evaluate_policy(
            action_id=action_id,
            proposal=proposal,
            role=role,
            workspace_mode=workspace_mode,
            order_value=order_value,
            value_limit=value_limit,
            has_conflict=has_conflict,
        )
        self._actions[action_id] = StoredAction(proposal, decision, role, tenant_id)
        self._idempotency[(tenant_id, proposal.idempotency_key)] = action_id
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type="policy_evaluated",
            actor_role=role,
            payload={
                "decision": decision.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
            },
        )
        return decision

    def restore(self, event: ActionEventRecord) -> None:
        if event.event_id in {
            existing.event_id
            for events in self._events.values()
            for existing in events
        }:
            return
        if event.event_type != "policy_evaluated":
            action = self._actions.get(event.action_id)
            if action is None:
                return
            self._apply_restored_event(action, event)
            self._events.setdefault(event.action_id, []).append(event)
            if event.event_type == "provider_accepted":
                receipt = ExecutionReceipt.model_validate(event.payload)
                self._executions[(event.tenant_id, receipt.idempotency_key)] = receipt
            return
        proposal_data = event.payload.get("proposal")
        decision_data = event.payload.get("decision")
        if not isinstance(proposal_data, dict) or not isinstance(decision_data, dict):
            raise ValueError("Policy evaluation event is missing proposal or decision.")
        proposal = ActionProposal.model_validate(proposal_data)
        decision = ActionDecision.model_validate(decision_data)
        self._actions[event.action_id] = StoredAction(
            proposal, decision, event.actor_role, event.tenant_id
        )
        self._idempotency[(event.tenant_id, proposal.idempotency_key)] = event.action_id
        self._events.setdefault(event.action_id, []).append(event)

    @staticmethod
    def _apply_restored_event(action: StoredAction, event: ActionEventRecord) -> None:
        status_map = {
            "approved": ActionStatus.approved,
            "rejected": ActionStatus.rejected,
            "approval_denied": ActionStatus.denied,
            "precondition_failed": ActionStatus.precondition_failed,
            "provider_accepted": ActionStatus.provider_accepted,
            "verification_pending": ActionStatus.verification_pending,
            "verified": ActionStatus.verified,
            "verification_failed": ActionStatus.verification_failed,
            "state_diverged": ActionStatus.state_diverged,
        }
        status = status_map.get(event.event_type)
        if status is not None:
            reason = str(event.payload.get("reason", event.event_type))
            action.decision = action.decision.model_copy(
                update={"status": status, "reason": reason}
            )

    def approve(
        self,
        action_id: str,
        approval: ApprovalRequest,
        role: str,
        tenant_id: str = "demo",
        current_state: OrderState | None = None,
    ) -> ActionDecision:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        if action.decision.status != ActionStatus.approval_required:
            return action.decision
        if role != action.decision.required_role:
            action.decision = action.decision.model_copy(
                update={
                    "status": ActionStatus.denied,
                    "reason": "Approver does not have the required role.",
                }
            )
            self._append_event(
                tenant_id=tenant_id,
                action_id=action_id,
                event_type="approval_denied",
                actor_role=role,
                payload={"reason": action.decision.reason},
            )
            return action.decision
        precondition_failure = self._check_preconditions(action.proposal, current_state)
        if precondition_failure is not None:
            action.decision = action.decision.model_copy(
                update={"status": ActionStatus.precondition_failed, "reason": precondition_failure}
            )
            self._append_event(
                tenant_id=tenant_id,
                action_id=action_id,
                event_type="precondition_failed",
                actor_role=role,
                payload={"reason": precondition_failure},
            )
            return action.decision
        action.decision = action.decision.model_copy(
            update={"status": ActionStatus.approved, "reason": approval.reason}
        )
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type="approved",
            actor_role=role,
            payload={"reason": approval.reason},
        )
        return action.decision

    @staticmethod
    def _check_preconditions(
        proposal: ActionProposal, current_state: OrderState | None
    ) -> str | None:
        if current_state is None:
            return "Target order does not exist in World State."
        if current_state.state_version != proposal.expected_state_version:
            return "Target state version changed since proposal."
        for name, expected in proposal.expected_attributes.items():
            attribute = current_state.attributes.get(name)
            if attribute is None or attribute.value != expected:
                return f"Expected attribute does not match current state: {name}."
        return None

    def reject(
        self, action_id: str, rejection: ApprovalRequest, tenant_id: str = "demo"
    ) -> ActionDecision:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        if action.decision.status != ActionStatus.approval_required:
            return action.decision
        action.decision = action.decision.model_copy(
            update={"status": ActionStatus.rejected, "reason": rejection.reason}
        )
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type="rejected",
            actor_role="approver",
            payload={"reason": rejection.reason},
        )
        return action.decision

    def events(self, action_id: str, tenant_id: str = "demo") -> list[ActionEventRecord]:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        return list(self._events.get(action_id, []))

    def get_proposal(self, action_id: str, tenant_id: str = "demo") -> ActionProposal:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        return action.proposal

    def get_decision(self, action_id: str, tenant_id: str = "demo") -> ActionDecision:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        return action.decision

    def list_actions(self, tenant_id: str = "demo") -> list[ActionDecision]:
        """Return the current decision for every action owned by ``tenant_id``."""
        return [
            action.decision
            for action in self._actions.values()
            if action.tenant_id == tenant_id
        ]

    #: Verification outcomes that end the polling loop.
    TERMINAL_VERIFICATION_STATUSES = frozenset(
        {
            ActionStatus.verified,
            ActionStatus.verification_failed,
            ActionStatus.state_diverged,
        }
    )

    #: Statuses from which a verification attempt may still be made.
    VERIFIABLE_STATUSES = frozenset(
        {ActionStatus.provider_accepted, ActionStatus.verification_pending}
    )

    def pending_verifications(self) -> list[tuple[str, str]]:
        """Return ``(tenant_id, action_id)`` pairs awaiting read-after-write verification."""
        return [
            (action.tenant_id, action_id)
            for action_id, action in self._actions.items()
            if action.decision.status in self.VERIFIABLE_STATUSES
        ]

    def verify(
        self,
        action_id: str,
        tenant_id: str,
        state: OrderState | None,
        *,
        is_final_attempt: bool = True,
    ) -> ActionDecision:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        if action.decision.status not in self.VERIFIABLE_STATUSES:
            raise ValueError("Only provider-accepted actions can be verified.")
        expected_status = "cancelled"
        observed = None
        if state is not None and "status" in state.attributes:
            observed = state.attributes["status"].value

        if observed == expected_status:
            status = ActionStatus.verified
            reason = "Independent read-after-write verification succeeded."
        elif not is_final_attempt:
            status = ActionStatus.verification_pending
            reason = (
                "Verification read has not yet observed the expected cancelled state."
                if observed is not None
                else "Verification read did not return an order status yet."
            )
        elif observed is None:
            status = ActionStatus.verification_failed
            reason = "Verification read did not return an order status before timeout."
        else:
            status = ActionStatus.state_diverged
            reason = (
                f"Verification read diverged from the expected cancelled state "
                f"(observed {observed!r})."
            )

        action.decision = action.decision.model_copy(update={"status": status, "reason": reason})
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type=status.value,
            actor_role="verifier",
            payload={
                "reason": reason,
                "commit_id": state.commit_id if state else None,
                "observed_status": observed,
            },
        )
        return action.decision

    _VERIFICATION_EVENT_TYPES = frozenset(
        {"verified", "verification_failed", "state_diverged", "verification_pending"}
    )

    def proof(
        self,
        action_id: str,
        tenant_id: str = "demo",
        *,
        commit: CommitRecord | None = None,
    ) -> ProofBundle:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        events = self.events(action_id, tenant_id)
        latest_by_type: dict[str, ActionEventRecord] = {e.event_type: e for e in events}

        proposer = self._actor_from(latest_by_type.get("policy_evaluated"))
        approver = self._actor_from(
            latest_by_type.get("approved") or latest_by_type.get("rejected")
        )
        policy = self._policy_evidence(latest_by_type.get("policy_evaluated"))
        provider = self._provider_evidence(action.proposal, latest_by_type.get("provider_accepted"))
        verification = self._verification_evidence(events)

        projection: ProjectionDelta | None = None
        if commit is not None:
            projection = ProjectionDelta(
                commit_id=commit.commit_id,
                commit_hash=commit.hash,
                previous_hash=commit.previous_hash,
                before=commit.before,
                after=commit.after,
                semantic_diff=commit.semantic_diff,
            )

        status = action.decision.status
        if status == ActionStatus.verified:
            assurance = "verified"
        elif provider is not None:
            assurance = "accepted"
        else:
            assurance = "observed"

        warnings: list[str] = []
        if proposer is not None and approver is not None and proposer.role == approver.role:
            warnings.append(
                f"Same role ({proposer.role}) proposed and approved this action "
                "(demo-mode separation-of-duties exception)."
            )
        if status != ActionStatus.verified:
            warnings.append(
                f"Action did not reach 'verified'; current status is '{status.value}'."
            )
        precondition = latest_by_type.get("precondition_failed")
        if precondition is not None:
            warnings.append(
                f"A precondition failed at "
                f"{precondition.payload.get('stage', 'lifecycle')}: "
                f"{precondition.payload.get('reason', 'unspecified')}"
            )

        return ProofBundle(
            action_id=action_id,
            tenant_id=tenant_id,
            status=status,
            assurance_level=assurance,
            proposal=action.proposal,
            proposer=proposer,
            approver=approver,
            policy=policy,
            idempotency_key=action.proposal.idempotency_key,
            provider=provider,
            verification=verification,
            projection=projection,
            hash_chain=[
                HashChainLink(
                    event_id=e.event_id,
                    event_type=e.event_type,
                    previous_event_hash=e.previous_event_hash,
                    event_hash=e.event_hash,
                )
                for e in events
            ],
            warnings=warnings,
            events=events,
            verification_commit_id=(
                verification.verification_commit_id if verification is not None else None
            ),
        )

    @staticmethod
    def _actor_from(event: ActionEventRecord | None) -> ActorIdentity | None:
        if event is None:
            return None
        reason = event.payload.get("reason")
        return ActorIdentity(
            role=event.actor_role,
            reason=str(reason) if isinstance(reason, str) else None,
            event_id=event.event_id,
            event_hash=event.event_hash,
        )

    @staticmethod
    def _policy_evidence(event: ActionEventRecord | None) -> PolicyEvidence | None:
        if event is None or not isinstance(event.payload.get("decision"), dict):
            return None
        decision = event.payload["decision"]
        return PolicyEvidence(
            status=ActionStatus(decision["status"]),
            matched_rule=decision.get("matched_rule"),
            reason=decision["reason"],
            policy_version=decision["policy_version"],
            required_role=decision.get("required_role"),
        )

    @staticmethod
    def _provider_evidence(
        proposal: ActionProposal, event: ActionEventRecord | None
    ) -> ProviderEvidence | None:
        if event is None:
            return None
        payload = event.payload
        fingerprint = hash_json(
            {
                "action_type": proposal.action_type.value,
                "target_entity": proposal.target_entity,
                "idempotency_key": proposal.idempotency_key,
                "parameters": proposal.parameters,
            }
        )
        return ProviderEvidence(
            provider=str(payload.get("provider", "")),
            provider_request_id=str(payload.get("provider_request_id", "")),
            request_fingerprint=fingerprint,
            idempotency_key=proposal.idempotency_key,
            accepted_status=str(payload.get("status", "")),
        )

    def _verification_evidence(
        self, events: list[ActionEventRecord]
    ) -> VerificationEvidence | None:
        attempts = [e for e in events if e.event_type in self._VERIFICATION_EVENT_TYPES]
        if not attempts:
            return None
        terminal = [e for e in attempts if e.event_type != "verification_pending"]
        last = terminal[-1] if terminal else attempts[-1]
        commit_id = last.payload.get("commit_id")
        observed = last.payload.get("observed_status")
        return VerificationEvidence(
            result=ActionStatus(last.event_type),
            reason=str(last.payload.get("reason", "")),
            observed_status=str(observed) if isinstance(observed, str) else None,
            attempts=len(attempts),
            verification_commit_id=commit_id if isinstance(commit_id, str) else None,
        )

    #: Order statuses that make a test cancellation ineligible.
    TERMINAL_ORDER_STATUSES = frozenset({"cancelled", "canceled", "closed", "voided"})

    def execute(
        self,
        action_id: str,
        tenant_id: str,
        cancel_order: CancelOrderExecutor,
        current_state: OrderState | None = None,
    ) -> ExecutionReceipt:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        execution_key = (tenant_id, action.proposal.idempotency_key)
        existing = self._executions.get(execution_key)
        if existing is not None:
            return existing
        if action.decision.status != ActionStatus.approved:
            raise ValueError("Only approved actions can be executed.")
        if action.proposal.action_type != "cancel_order":
            raise ValueError("Only cancel_order is executable in the MVP.")
        self._require_eligible_test_order(action_id, tenant_id, current_state)
        order_id = action.proposal.target_entity.removeprefix("order:")
        receipt = cancel_order(action_id, order_id, action.proposal.idempotency_key)
        action.decision = action.decision.model_copy(
            update={"status": ActionStatus.provider_accepted, "reason": "Provider accepted write."}
        )
        self._executions[execution_key] = receipt
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type="provider_accepted",
            actor_role="system",
            payload=receipt.model_dump(mode="json"),
        )
        return receipt

    def _require_eligible_test_order(
        self, action_id: str, tenant_id: str, current_state: OrderState | None
    ) -> None:
        reason: str | None = None
        if current_state is None:
            reason = "Target order is not present in World State."
        else:
            status_attr = current_state.attributes.get("status")
            status = status_attr.value if status_attr is not None else None
            fulfillment_attr = current_state.attributes.get("fulfillment_status")
            fulfillment = fulfillment_attr.value if fulfillment_attr is not None else None
            if isinstance(status, str) and status.lower() in self.TERMINAL_ORDER_STATUSES:
                reason = f"Target order is already {status}; test cancellation is not eligible."
            elif isinstance(fulfillment, str) and fulfillment.lower() == "fulfilled":
                reason = "Target order is fulfilled and not eligible for test cancellation."
        if reason is None:
            return
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type="precondition_failed",
            actor_role="system",
            payload={"reason": reason, "stage": "execution"},
        )
        raise ValueError(reason)

    def _append_event(
        self,
        *,
        tenant_id: str,
        action_id: str,
        event_type: str,
        actor_role: str,
        payload: dict[str, object],
    ) -> None:
        action_events = self._events.get(action_id, [])
        previous_hash = action_events[-1].event_hash if action_events else None
        event_id = f"evt_{uuid4().hex[:16]}"
        event_hash = hash_json(
            {
                "event_id": event_id,
                "tenant_id": tenant_id,
                "action_id": action_id,
                "event_type": event_type,
                "actor_role": actor_role,
                "payload": payload,
                "previous_event_hash": previous_hash,
            }
        )
        event = ActionEventRecord(
            event_id=event_id,
            tenant_id=tenant_id,
            action_id=action_id,
            event_type=event_type,
            actor_role=actor_role,
            payload=payload,
            previous_event_hash=previous_hash,
            event_hash=event_hash,
        )
        self._events.setdefault(action_id, []).append(event)

    @staticmethod
    def _check_tenant(action: StoredAction, tenant_id: str) -> None:
        if action.tenant_id != tenant_id:
            raise KeyError("Unknown action")

    def _get(self, action_id: str) -> StoredAction:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise KeyError(f"Unknown action: {action_id}") from exc
