from datetime import UTC, datetime

from fastapi.testclient import TestClient

from reality_layer.api.app import create_app


def _observation(observation_id: str, object_type: str, object_id: str) -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "connector": "shopify" if object_type == "order" else "easypost",
        "object_type": object_type,
        "object_id": object_id,
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {"id": object_id, "status": "open"},
    }


def test_world_state_and_entity_queries_return_tenant_scoped_entities() -> None:
    client = TestClient(create_app())
    client.post(
        "/v1/observations",
        json=_observation("obs_order_1", "order", "order-1"),
        headers={"X-Reality-Tenant": "tenant-a"},
    )
    client.post(
        "/v1/observations",
        json=_observation("obs_shipment_1", "shipment", "shipment-1"),
        headers={"X-Reality-Tenant": "tenant-a"},
    )
    client.post(
        "/v1/observations",
        json=_observation("obs_order_2", "order", "order-2"),
        headers={"X-Reality-Tenant": "tenant-b"},
    )

    response = client.get(
        "/v1/world-state", headers={"X-Reality-Tenant": "tenant-a"}
    )
    assert response.status_code == 200
    assert [item["entity_id"] for item in response.json()] == [
        "order:order-1",
        "shipment:shipment-1",
    ]

    orders = client.get(
        "/v1/entities?entity_type=order",
        headers={"X-Reality-Tenant": "tenant-a"},
    )
    assert [item["entity_id"] for item in orders.json()] == ["order:order-1"]

    entity = client.get(
        "/v1/entities/order/order-1",
        headers={"X-Reality-Tenant": "tenant-a"},
    )
    assert entity.status_code == 200
    assert entity.json()["entity_id"] == "order:order-1"

    hidden = client.get(
        "/v1/entities/order/order-1",
        headers={"X-Reality-Tenant": "tenant-b"},
    )
    assert hidden.status_code == 404


def test_generic_entity_query_rejects_unknown_entity_type() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/entities/customer/customer-1")

    assert response.status_code == 404
