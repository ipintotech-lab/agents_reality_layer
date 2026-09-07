from dataclasses import dataclass
from uuid import uuid4

from reality_layer.actions.models import (
    ActionDecision,
    ActionEventRecord,
    ActionProposal,
    ActionStatus,
    ApprovalRequest,
)
from reality_layer.actions.policy import evaluate_policy
from reality_layer.reality_git import hash_json


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

    def approve(
        self, action_id: str, approval: ApprovalRequest, role: str, tenant_id: str = "demo"
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
