from datetime import UTC, datetime

from fastapi.testclient import TestClient

from reality_layer.api.app import create_app
from reality_layer.config import Settings


def _proposal() -> dict[str, object]:
    return {
        "action_type": "cancel_order",
        "target_entity": "order:shopify-123",
        "parameters": {},
        "reason": "Duplicate test order",
        "evidence_refs": ["obs_123"],
        "idempotency_key": "demo-cancel-order-123",
        "expected_state_version": 1,
        "expected_attributes": {"status": "open"},
    }


def _observe(client: TestClient, **payload: object) -> None:
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_shopify_gov",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", **payload},
        },
    )


def test_observe_only_workspace_denies_writes() -> None:
    client = TestClient(create_app(settings=Settings(workspace_mode="observe_only")))
    _observe(client, status="open")

    response = client.post(
        "/v1/actions", json=_proposal(), headers={"X-Reality-Role": "operations"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "denied"
    assert body["matched_rule"] == "deny.workspace.observe_only"


def test_order_value_above_threshold_is_denied() -> None:
    client = TestClient(create_app(settings=Settings(write_value_limit=100.0)))
    _observe(client, status="open", total_price="150.00")

    body = client.post(
        "/v1/actions", json=_proposal(), headers={"X-Reality-Role": "operations"}
    ).json()

    assert body["status"] == "denied"
    assert body["matched_rule"] == "deny.threshold.value"


def test_order_value_below_threshold_still_requires_approval() -> None:
    client = TestClient(create_app(settings=Settings(write_value_limit=100.0)))
    _observe(client, status="open", total_price="42.00")

    body = client.post(
        "/v1/actions", json=_proposal(), headers={"X-Reality-Role": "operations"}
    ).json()

    assert body["status"] == "approval_required"


def test_execute_refuses_already_cancelled_order_without_calling_provider() -> None:
    client = TestClient(create_app())
    _observe(client, status="open")
    action = client.post(
        "/v1/actions", json=_proposal(), headers={"X-Reality-Role": "operations"}
    ).json()
    client.post(
        f"/v1/actions/{action['action_id']}/approve",
        json={"reason": "approved"},
        headers={"X-Reality-Role": "operations"},
    )
    # Order is independently cancelled before execution runs.
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_shopify_gov_cancelled",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", "status": "cancelled"},
        },
    )

    response = client.post(f"/v1/actions/{action['action_id']}/execute")

    assert response.status_code == 409
    events = client.get(f"/v1/actions/{action['action_id']}/events").json()
    assert events[-1]["event_type"] == "precondition_failed"
    assert events[-1]["payload"]["stage"] == "execution"
