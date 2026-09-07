from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from reality_layer.actions.models import (
    ActionDecision,
    ActionEventRecord,
    ActionProposal,
    ActionStatus,
    ApprovalRequest,
    ExecutionReceipt,
    ProofBundle,
)
from reality_layer.actions.policy import evaluate_policy
from reality_layer.reality_git import hash_json
from reality_layer.world_state.models import OrderState


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
        self, proposal: ActionProposal, role: str, tenant_id: str = "demo"
    ) -> ActionDecision:
        existing_id = self._idempotency.get((tenant_id, proposal.idempotency_key))
        if existing_id is not None:
            return self._actions[existing_id].decision

        action_id = f"act_{uuid4().hex[:16]}"
        decision = evaluate_policy(action_id=action_id, proposal=proposal, role=role)
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
        if event.event_type != "policy_evaluated":
            action = self._actions.get(event.action_id)
            if action is None:
                return
            self._apply_restored_event(action, event)
            self._events.setdefault(event.action_id, []).append(event)
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
            "verified": ActionStatus.verified,
            "verification_failed": ActionStatus.verification_failed,
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

    def verify(
        self, action_id: str, tenant_id: str, state: OrderState | None
    ) -> ActionDecision:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        if action.decision.status != ActionStatus.provider_accepted:
            raise ValueError("Only provider-accepted actions can be verified.")
        expected_status = "cancelled"
        if state is None or state.attributes.get("status") is None:
            reason = "Verification read did not return an order status."
            status = ActionStatus.verification_failed
        elif state.attributes["status"].value != expected_status:
            reason = "Verification read diverged from the expected cancelled state."
            status = ActionStatus.verification_failed
        else:
            reason = "Independent read-after-write verification succeeded."
            status = ActionStatus.verified
        action.decision = action.decision.model_copy(update={"status": status, "reason": reason})
        self._append_event(
            tenant_id=tenant_id,
            action_id=action_id,
            event_type=status.value,
            actor_role="verifier",
            payload={"reason": reason, "commit_id": state.commit_id if state else None},
        )
        return action.decision

    def proof(self, action_id: str, tenant_id: str = "demo") -> ProofBundle:
        action = self._get(action_id)
        self._check_tenant(action, tenant_id)
        assurance = "verified" if action.decision.status == ActionStatus.verified else "accepted"
        verification_events = [
            event for event in self._events.get(action_id, []) if event.event_type == "verified"
        ]
        commit_id = (
            verification_events[-1].payload.get("commit_id") if verification_events else None
        )
        return ProofBundle(
            action_id=action_id,
            tenant_id=tenant_id,
            status=action.decision.status,
            assurance_level=assurance,
            proposal=action.proposal,
            events=self.events(action_id, tenant_id),
            verification_commit_id=commit_id if isinstance(commit_id, str) else None,
        )

    def execute(
        self,
        action_id: str,
        tenant_id: str,
        cancel_order: CancelOrderExecutor,
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
