from typing import Any

from reality_layer.actions.models import ActionStatus, ExecutionReceipt
from reality_layer.connectors.http import HttpTransport, UrlLibTransport


class ShopifyHttpClient:
    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        transport: HttpTransport | None = None,
    ) -> None:
        if not shop_domain or not access_token:
            raise ValueError("Shopify domain and access token are required")
        self.base_url = f"https://{shop_domain}/admin/api/2025-01"
        self.access_token = access_token
        self.transport = transport or UrlLibTransport()

    def health_check(self) -> bool:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/shop.json",
            {"X-Shopify-Access-Token": self.access_token, "Accept": "application/json"},
        )
        return response.status_code == 200

    def read_order(self, order_id: str) -> dict[str, Any]:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/orders/{order_id}.json",
            {"X-Shopify-Access-Token": self.access_token, "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Shopify order read failed with status {response.status_code}")
        order = response.payload.get("order")
        if not isinstance(order, dict):
            raise ValueError("Shopify response did not contain an order")
        return order

    def list_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/orders.json?status=any&limit={limit}",
            {"X-Shopify-Access-Token": self.access_token, "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Shopify order list failed with status {response.status_code}")
        orders = response.payload.get("orders")
        if not isinstance(orders, list) or not all(isinstance(order, dict) for order in orders):
            raise ValueError("Shopify response did not contain orders")
        return orders

    def cancel_order(self, action_id: str, order_id: str, idempotency_key: str) -> ExecutionReceipt:
        response = self.transport.request(
            "POST",
            f"{self.base_url}/orders/{order_id}/close.json",
            {
                "X-Shopify-Access-Token": self.access_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )
        if response.status_code not in {200, 201, 202}:
            raise RuntimeError(
                f"Shopify order cancellation failed with status {response.status_code}"
            )
        return ExecutionReceipt(
            action_id=action_id,
            status=ActionStatus.provider_accepted,
            provider="shopify",
            provider_request_id=f"shopify-http-{order_id}",
            idempotency_key=idempotency_key,
        )


class EasyPostHttpClient:
    def __init__(
        self,
        api_key: str,
        transport: HttpTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("EasyPost API key is required")
        self.base_url = "https://api.easypost.com/v2"
        self.api_key = api_key
        self.transport = transport or UrlLibTransport()

    def health_check(self) -> bool:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/api_keys",
            {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
        )
        return response.status_code == 200

    def read_tracker(self, tracker_id: str) -> dict[str, Any]:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/trackers/{tracker_id}",
            {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"EasyPost tracker read failed with status {response.status_code}")
        tracker = response.payload.get("tracker")
        if not isinstance(tracker, dict):
            raise ValueError("EasyPost response did not contain a tracker")
        return tracker

    def list_trackers(self, limit: int = 10) -> list[dict[str, Any]]:
        response = self.transport.request(
            "GET",
            f"{self.base_url}/trackers?limit={limit}",
            {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"EasyPost tracker list failed with status {response.status_code}")
        trackers = response.payload.get("trackers")
        if not isinstance(trackers, list) or not all(
            isinstance(tracker, dict) for tracker in trackers
        ):
            raise ValueError("EasyPost response did not contain trackers")
        return trackers
