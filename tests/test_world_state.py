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


def test_conflicting_sources_are_detected_and_prior_value_is_kept() -> None:
    from reality_layer.world_state import Observation, WorldStateService

    service = WorldStateService()
    service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_carrier_1",
            connector="carrier-api",
            object_type="shipment",
            object_id="shp_1",
            observed_at=datetime.now(UTC),
            payload={"id": "shp_1", "status": "delayed"},
        ),
    )
    state = service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_erp_1",
            connector="erp",
            object_type="shipment",
            object_id="shp_1",
            observed_at=datetime.now(UTC),
            payload={"id": "shp_1", "status": "shipped"},
        ),
    )

    assert state.attributes["status"].value == "delayed"
    assert service.has_open_conflicts("tenant_a", "shipment", "shp_1")
    conflicts = service.list_conflicts("tenant_a")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.attribute == "status"
    assert conflict.status == "open"
    assert {candidate.value for candidate in conflict.candidates} == {"delayed", "shipped"}
    assert {candidate.connector for candidate in conflict.candidates} == {"carrier-api", "erp"}


def test_same_connector_correction_is_not_a_conflict() -> None:
    from reality_layer.world_state import Observation, WorldStateService

    service = WorldStateService()
    service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_shopify_1",
            connector="shopify",
            object_type="order",
            object_id="order_1",
            observed_at=datetime.now(UTC),
            payload={"id": "order_1", "status": "open"},
        ),
    )
    state = service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_shopify_2",
            connector="shopify",
            object_type="order",
            object_id="order_1",
            observed_at=datetime.now(UTC),
            payload={"id": "order_1", "status": "paid"},
        ),
    )

    assert state.attributes["status"].value == "paid"
    assert not service.has_open_conflicts("tenant_a", "order", "order_1")


def test_resolving_a_conflict_updates_state_and_creates_a_commit() -> None:
    from reality_layer.world_state import Observation, WorldStateService

    service = WorldStateService()
    service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_carrier_1",
            connector="carrier-api",
            object_type="shipment",
            object_id="shp_1",
            observed_at=datetime.now(UTC),
            payload={"id": "shp_1", "status": "delayed"},
        ),
    )
    service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_erp_1",
            connector="erp",
            object_type="shipment",
            object_id="shp_1",
            observed_at=datetime.now(UTC),
            payload={"id": "shp_1", "status": "shipped"},
        ),
    )
    conflict = service.list_conflicts("tenant_a")[0]
    version_before = service.get_entity("tenant_a", "shipment", "shp_1").state_version

    resolved = service.resolve_conflict(
        "tenant_a", conflict.conflict_id, "shipped", "operator@example.com", "carrier lagged"
    )

    assert resolved.status == "resolved"
    assert resolved.resolved_value == "shipped"
    assert not service.has_open_conflicts("tenant_a", "shipment", "shp_1")
    state = service.get_entity("tenant_a", "shipment", "shp_1")
    assert state.attributes["status"].value == "shipped"
    assert state.attributes["status"].connector == "operator"
    assert state.state_version == version_before + 1
    commit = service.get_commit_for_state("tenant_a", state)
    assert commit.cause == f"conflict_resolved:{conflict.conflict_id}"


def test_conflicts_api_lists_gets_and_resolves() -> None:
    client = TestClient(create_app())
    headers = {"X-Reality-Tenant": "tenant_a"}

    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_carrier_1",
            "connector": "carrier-api",
            "object_type": "shipment",
            "object_id": "shp_1",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shp_1", "status": "delayed"},
        },
        headers=headers,
    )
    client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_erp_1",
            "connector": "erp",
            "object_type": "shipment",
            "object_id": "shp_1",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "shp_1", "status": "shipped"},
        },
        headers=headers,
    )

    listed = client.get("/v1/conflicts", headers=headers)
    assert listed.status_code == 200
    conflicts = listed.json()
    assert len(conflicts) == 1
    conflict_id = conflicts[0]["conflict_id"]

    fetched = client.get(f"/v1/conflicts/{conflict_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["conflict_id"] == conflict_id

    missing = client.get("/v1/conflicts/does-not-exist", headers=headers)
    assert missing.status_code == 404

    denied = client.post(
        f"/v1/conflicts/{conflict_id}/resolve",
        json={"resolved_value": "shipped", "reason": "carrier lagged"},
        headers={**headers, "X-Reality-Role": "observer"},
    )
    assert denied.status_code == 403

    resolved = client.post(
        f"/v1/conflicts/{conflict_id}/resolve",
        json={"resolved_value": "shipped", "reason": "carrier lagged"},
        headers={**headers, "X-Reality-Role": "operations"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    after_resolve = client.get("/v1/conflicts?status=open", headers=headers)
    assert after_resolve.json() == []


def test_hydrating_old_state_does_not_reset_latest_commit_cursor() -> None:
    from reality_layer.world_state import Observation, WorldStateService

    service = WorldStateService()
    first = service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_old",
            connector="shopify",
            object_type="order",
            object_id="shopify-123",
            observed_at=datetime.now(UTC),
            payload={"id": "shopify-123", "status": "open"},
        ),
    )
    second = service.ingest(
        "tenant_a",
        Observation(
            observation_id="obs_new",
            connector="shopify",
            object_type="order",
            object_id="shopify-123",
            observed_at=datetime.now(UTC),
            payload={"id": "shopify-123", "status": "paid"},
        ),
    )

    first_commit = service.get_commit_for_state("tenant_a", first)
    second_commit = service.get_commit_for_state("tenant_a", second)

    service.hydrate(first, first_commit.commit_id, first_commit.hash)

    assert [commit.commit_id for commit in service.list_commits("tenant_a")] == [
        first_commit.commit_id,
        second_commit.commit_id,
    ]
