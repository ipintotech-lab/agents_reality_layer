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


def test_dashboard_page_is_served_at_root() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Reality Layer</title>" in response.text
    assert "/v1/world-state" in response.text
    assert "/v1/actions" in response.text


def test_list_actions_is_tenant_scoped() -> None:
    client = TestClient(create_app())
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_dash",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "shopify-123",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shopify-123", "status": "open"},
        },
        headers={"X-Reality-Tenant": "tenant_a"},
    )
    created = client.post(
        "/v1/actions",
        json=proposal(),
        headers={"X-Reality-Role": "operations", "X-Reality-Tenant": "tenant_a"},
    ).json()

    listed = client.get("/v1/actions", headers={"X-Reality-Tenant": "tenant_a"})
    assert listed.status_code == 200
    payload = listed.json()
    assert [a["action_id"] for a in payload] == [created["action_id"]]
    assert payload[0]["status"] == "approval_required"

    other = client.get("/v1/actions", headers={"X-Reality-Tenant": "tenant_b"})
    assert other.json() == []
