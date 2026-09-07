from fastapi.testclient import TestClient

from reality_layer.api.app import create_app


def proposal() -> dict[str, object]:
    return {
        "action_type": "cancel_order",
        "target_entity": "order:shopify-123",
        "parameters": {},
        "reason": "Duplicate test order",
        "evidence_refs": ["obs_123"],
        "idempotency_key": "demo-cancel-order-123",
    }


def test_operations_cancel_requires_approval_then_can_be_approved() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/actions", json=proposal(), headers={"X-Reality-Role": "operations"})

    assert response.status_code == 201
    action = response.json()
    assert action["status"] == "approval_required"
    assert action["required_role"] == "operations"

    approved = client.post(
        f"/v1/actions/{action['action_id']}/approve",
        json={"reason": "Confirmed duplicate in Shopify test store"},
        headers={"X-Reality-Role": "operations"},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_observer_is_denied_and_does_not_create_approval_path() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/actions", json=proposal())

    assert response.status_code == 201
    assert response.json()["status"] == "denied"
    assert response.json()["matched_rule"] == "deny.observer.write"


def test_idempotency_returns_same_action_decision() -> None:
    client = TestClient(create_app())

    first = client.post(
        "/v1/actions", json=proposal(), headers={"X-Reality-Role": "operations"}
    ).json()
    second = client.post(
        "/v1/actions", json=proposal(), headers={"X-Reality-Role": "operations"}
    ).json()

    assert second == first


def test_action_events_form_a_hash_linked_audit_chain() -> None:
    client = TestClient(create_app())

    action = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations", "X-Reality-Tenant": "tenant_a"},
    ).json()
    client.post(
        f"/v1/actions/{action['action_id']}/approve",
        json={"reason": "Approved for demo"},
        headers={"X-Reality-Role": "operations", "X-Reality-Tenant": "tenant_a"},
    )

    response = client.get(
        f"/v1/actions/{action['action_id']}/events",
        headers={"X-Reality-Tenant": "tenant_a"},
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["event_type"] for event in events] == ["policy_evaluated", "approved"]
    assert events[0]["previous_event_hash"] is None
    assert events[1]["previous_event_hash"] == events[0]["event_hash"]


def test_action_events_are_tenant_scoped() -> None:
    client = TestClient(create_app())

    action = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations", "X-Reality-Tenant": "tenant_a"},
    ).json()
    response = client.get(
        f"/v1/actions/{action['action_id']}/events",
        headers={"X-Reality-Tenant": "tenant_b"},
    )

    assert response.status_code == 404


def test_unknown_action_returns_not_found() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/actions/act_missing/reject",
        json={"reason": "Not applicable"},
    )

    assert response.status_code == 404
