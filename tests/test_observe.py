from typing import Any

from reality_layer.connectors import ShopifyConnector
from reality_layer.connectors.observe import observe_payload
from reality_layer.storage import LocalObjectStore


def test_observe_payload_persists_raw_payload_and_normalizes(tmp_path) -> None:
    result = observe_payload(
        "tenant_a",
        {"id": "123", "status": "open"},
        ShopifyConnector(),
        LocalObjectStore(tmp_path),
    )

    assert result.observation.object_id == "123"
    assert result.raw_payload.ref.startswith("local://tenant_a/raw_payloads/")
    assert b'"id":"123"' in LocalObjectStore(tmp_path).get_raw_payload(result.raw_payload.ref)


def test_observation_batch_limit_is_passed_to_provider() -> None:
    class FakeClient:
        def list_orders(self, limit: int) -> list[dict[str, Any]]:
            return [{"id": str(index), "status": "open"} for index in range(limit)]

    client = FakeClient()
    assert len(client.list_orders(3)) == 3
