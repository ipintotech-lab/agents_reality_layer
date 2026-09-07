from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from reality_layer.api.app import create_app


def observation(observation_id: str = "obs_shopify_1") -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "connector": "shopify",
        "object_type": "order",
        "object_id": "shopify-123",
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {"id": "shopify-123", "status": "open", "currency": "USD"},
    }


def test_observation_projects_order_state_with_provenance() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/observations",
        json=observation(),
        headers={"X-Reality-Tenant": "tenant_a"},
    )

    assert response.status_code == 201
    state = response.json()
    assert state["entity_id"] == "order:shopify-123"
    assert state["state_version"] == 1
    assert state["attributes"]["status"]["value"] == "open"
    assert state["attributes"]["status"]["source_observation_ids"] == ["obs_shopify_1"]
    assert state["attributes"]["status"]["freshness"] == "fresh"


def test_duplicate_observation_is_idempotent() -> None:
    client = TestClient(create_app())
    headers = {"X-Reality-Tenant": "tenant_a"}

    first = client.post("/v1/observations", json=observation(), headers=headers).json()
    second = client.post("/v1/observations", json=observation(), headers=headers).json()

    assert second == first


def test_new_observation_without_effective_change_does_not_create_commit() -> None:
    client = TestClient(create_app())
    first = client.post("/v1/observations", json=observation("obs_noop_1")).json()
    second = client.post("/v1/observations", json=observation("obs_noop_2")).json()

    assert second == first


def test_stale_observation_is_marked_stale() -> None:
    client = TestClient(create_app())
    stale = observation("obs_stale")
    stale["observed_at"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()

    response = client.post("/v1/observations", json=stale)

    assert response.status_code == 201
    assert response.json()["attributes"]["status"]["freshness"] == "stale"


def test_order_reads_are_tenant_scoped() -> None:
    client = TestClient(create_app())
    client.post(
        "/v1/observations",
        json=observation(),
        headers={"X-Reality-Tenant": "tenant_a"},
    )

    response = client.get("/v1/orders/shopify-123", headers={"X-Reality-Tenant": "tenant_b"})

    assert response.status_code == 404


def test_shipment_observation_can_be_read_as_world_state() -> None:
    client = TestClient(create_app())
    payload = observation("obs_shipment")
    payload["object_type"] = "shipment"
    payload["object_id"] = "shp_123"
    payload["payload"] = {"id": "shp_123", "status": "in_transit"}

    ingested = client.post("/v1/observations", json=payload)
    response = client.get("/v1/shipments/shp_123")

    assert ingested.status_code == 201
    assert response.status_code == 200
    assert response.json()["entity_id"] == "shipment:shp_123"


def test_projection_creates_hash_linked_semantic_commit() -> None:
    client = TestClient(create_app())
    headers = {"X-Reality-Tenant": "tenant_a"}

    first = client.post("/v1/observations", json=observation(), headers=headers).json()
    changed = observation("obs_shopify_2")
    changed["payload"]["status"] = "cancelled"
    second = client.post("/v1/observations", json=changed, headers=headers).json()

    first_commit = client.get(f"/v1/commits/{first['commit_id']}", headers=headers).json()
    second_commit = client.get(f"/v1/commits/{second['commit_id']}", headers=headers).json()

    assert first_commit["semantic_diff"]["attributes_changed"] == ["currency", "id", "status"]
    assert second_commit["semantic_diff"]["attributes_changed"] == ["status"]
    assert second_commit["parent_commit_id"] == first["commit_id"]
    assert second_commit["previous_hash"] == first_commit["hash"]


def test_commit_reads_are_tenant_scoped() -> None:
    client = TestClient(create_app())
    first = client.post("/v1/observations", json=observation()).json()

    response = client.get(
        f"/v1/commits/{first['commit_id']}",
        headers={"X-Reality-Tenant": "tenant_b"},
    )

    assert response.status_code == 404
