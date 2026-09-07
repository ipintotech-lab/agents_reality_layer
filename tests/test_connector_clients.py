from typing import Any

import pytest

from reality_layer.connectors import EasyPostHttpClient, ShopifyHttpClient
from reality_layer.connectors.http import HttpResponse


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def request(
        self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
    ) -> HttpResponse:
        self.calls.append((method, url, headers))
        return self.response


def test_shopify_http_client_health_and_cancel() -> None:
    transport = FakeTransport(HttpResponse(200, {"order": {"id": "123"}}))
    client = ShopifyHttpClient("shop.example", "secret", transport)

    assert client.health_check()
    receipt = client.cancel_order("act_1", "123", "cancel:tenant:123:1")

    assert receipt.provider == "shopify"
    assert transport.calls[-1][0] == "POST"
    assert transport.calls[-1][2]["Idempotency-Key"] == "cancel:tenant:123:1"


def test_easypost_http_client_reads_tracker() -> None:
    transport = FakeTransport(
        HttpResponse(200, {"tracker": {"id": "trk_1", "status": "in_transit"}})
    )
    client = EasyPostHttpClient("secret", transport)

    assert client.read_tracker("trk_1")["status"] == "in_transit"
    assert transport.calls[0][2]["Authorization"] == "Bearer secret"


def test_clients_require_credentials() -> None:
    with pytest.raises(ValueError):
        ShopifyHttpClient("", "secret")
    with pytest.raises(ValueError):
        EasyPostHttpClient("")
