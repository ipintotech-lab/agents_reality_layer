from datetime import UTC, datetime

import pytest

from reality_layer.connectors import EasyPostConnector, ShopifyConnector


def test_shopify_connector_normalizes_order_observation() -> None:
    observation = ShopifyConnector().normalize(
        {
            "id": "gid://shopify/Order/123",
            "financial_status": "paid",
            "currency": "USD",
            "updated_at": "2026-09-07T12:00:00Z",
        }
    )

    assert observation.connector == "shopify"
    assert observation.object_type == "order"
    assert observation.payload["status"] == "paid"
    assert observation.observed_at == datetime(2026, 9, 7, 12, tzinfo=UTC)


def test_easypost_connector_normalizes_shipment_observation() -> None:
    observation = EasyPostConnector().normalize(
        {
            "id": "shp_123",
            "tracking_code": "940011",
            "status": "in_transit",
        }
    )

    assert observation.connector == "easypost"
    assert observation.object_type == "shipment"
    assert observation.payload["tracking_code"] == "940011"


@pytest.mark.parametrize(
    ("connector", "payload"),
    [
        (ShopifyConnector(), {"financial_status": "paid"}),
        (EasyPostConnector(), {"id": "shp_123", "status": "in_transit"}),
    ],
)
def test_connectors_reject_incomplete_payloads(connector, payload) -> None:
    with pytest.raises(ValueError):
        connector.normalize(payload)
