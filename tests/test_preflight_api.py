from fastapi.testclient import TestClient

from reality_layer.api.app import create_app
from reality_layer.config import Settings


def test_preflight_api_returns_sanitized_connector_requirements() -> None:
    client = TestClient(create_app(settings=Settings()))

    response = client.get(
        "/v1/preflight",
        params={"order_id": "order-1", "shipment_id": "shp-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert "shopify.authenticated" in body["failures"]
    assert body["demo_order"]["failures"] == ["order.connector_unavailable"]
    assert body["demo_shipment"]["failures"] == ["shipment.connector_unavailable"]
    assert "access_token" not in response.text.lower()
