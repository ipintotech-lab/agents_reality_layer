from datetime import UTC, datetime

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
        "expected_state_version": 1,
        "expected_attributes": {"status": "open"},
    }


def test_operations_cancel_requires_approval_then_can_be_approved() -> None:
    client = TestClient(create_app())
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_shopify_action",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", "status": "open"},
        },
    )

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
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_shopify_event",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", "status": "open"},
        },
        headers={"X-Reality-Tenant": "tenant_a"},
    )

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


def test_approval_fails_when_world_state_version_is_stale() -> None:
    client = TestClient(create_app())
    client.post("/v1/observations", json={
        "observation_id": "obs_state_1",
        "connector": "shopify",
        "object_type": "order",
        "object_id": "shopify-123",
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {"id": "shopify-123", "status": "open"},
    })
    client.post("/v1/observations", json={
        "observation_id": "obs_state_2",
        "connector": "shopify",
        "object_type": "order",
        "object_id": "shopify-123",
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {"id": "shopify-123", "status": "processing"},
    })

    action = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations"},
    ).json()
    response = client.post(
        f"/v1/actions/{action['action_id']}/approve",
        json={"reason": "State changed"},
        headers={"X-Reality-Role": "operations"},
    )

    assert response.json()["status"] == "precondition_failed"


def test_approved_cancel_can_execute_once_and_returns_provider_accepted() -> None:
    client = TestClient(create_app())
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_execute",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", "status": "open"},
        },
    )
    action = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations"},
    ).json()
    client.post(
        f"/v1/actions/{action['action_id']}/approve",
        json={"reason": "Approved for test execution"},
        headers={"X-Reality-Role": "operations"},
    )

    first = client.post(f"/v1/actions/{action['action_id']}/execute").json()
    second = client.post(f"/v1/actions/{action['action_id']}/execute").json()

    assert first["status"] == "provider_accepted"
    assert second == first


def test_unapproved_action_cannot_execute() -> None:
    client = TestClient(create_app())
    action = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations"},
    ).json()

    response = client.post(f"/v1/actions/{action['action_id']}/execute")

    assert response.status_code == 409


def test_verified_action_returns_proof_bundle() -> None:
    client = TestClient(create_app())
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_verify",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", "status": "open"},
        },
    )
    action = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations"},
    ).json()
    client.post(
        f"/v1/actions/{action['action_id']}/approve",
        json={"reason": "Approved for verification"},
        headers={"X-Reality-Role": "operations"},
    )
    client.post(f"/v1/actions/{action['action_id']}/execute")

    verified = client.post(f"/v1/actions/{action['action_id']}/verify")
    proof = client.get(f"/v1/actions/{action['action_id']}/proof")

    assert verified.json()["status"] == "verified"
    assert proof.status_code == 200
    assert proof.json()["assurance_level"] == "verified"
    assert proof.json()["verification_commit_id"].startswith("cmt_")
    assert proof.json()["events"][-1]["event_type"] == "verified"


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
