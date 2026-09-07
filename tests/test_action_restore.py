from reality_layer.actions.models import ActionEventRecord, ActionStatus
from reality_layer.actions.service import ActionService


def test_restore_provider_acceptance_rehydrates_execution_idempotency() -> None:
    service = ActionService()
    service.restore(
        ActionEventRecord(
            event_id="evt_policy",
            tenant_id="tenant_a",
            action_id="act_1",
            event_type="policy_evaluated",
            actor_role="operations",
            payload={
                "proposal": {
                    "action_type": "cancel_order",
                    "target_entity": "order:123",
                    "parameters": {},
                    "reason": "test",
                    "evidence_refs": [],
                    "idempotency_key": "cancel-tenant-a-123",
                    "expected_state_version": 1,
                    "expected_attributes": {"status": "open"},
                },
                "decision": {
                    "action_id": "act_1",
                    "status": "approved",
                    "reason": "approved",
                    "policy_version": "mvp-1",
                    "required_role": "operations",
                },
            },
            event_hash="sha256:policy",
        )
    )
    service.restore(
        ActionEventRecord(
            event_id="evt_provider",
            tenant_id="tenant_a",
            action_id="act_1",
            event_type="provider_accepted",
            actor_role="system",
            payload={
                "action_id": "act_1",
                "status": "provider_accepted",
                "provider": "shopify",
                "provider_request_id": "req_1",
                "idempotency_key": "cancel-tenant-a-123",
            },
            event_hash="sha256:provider",
        )
    )

    calls = 0

    def executor(action_id: str, order_id: str, idempotency_key: str):
        nonlocal calls
        calls += 1
        raise AssertionError("restored execution must not call the provider")

    receipt = service.execute("act_1", "tenant_a", executor)

    assert receipt.provider_request_id == "req_1"
    assert receipt.status == ActionStatus.provider_accepted
    assert calls == 0
