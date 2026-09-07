from typing import Any
from uuid import uuid4

from reality_layer.actions.models import ActionStatus, ExecutionReceipt
from reality_layer.connectors.base import observation_token, observed_at, required_string
from reality_layer.world_state.models import Observation


class ShopifyConnector:
    name = "shopify"

    def __init__(self) -> None:
        self._cancelled_orders: set[str] = set()

    def cancel_order(
        self, action_id: str, order_id: str, idempotency_key: str
    ) -> ExecutionReceipt:
        self._cancelled_orders.add(order_id)
        return ExecutionReceipt(
            action_id=action_id,
            status=ActionStatus.provider_accepted,
            provider=self.name,
            provider_request_id=f"shopify-test-{uuid4().hex[:12]}",
            idempotency_key=idempotency_key,
        )

    def read_order(self, order_id: str) -> dict[str, Any]:
        status = "cancelled" if order_id in self._cancelled_orders else "open"
        return {"id": order_id, "status": status}

    def normalize(self, payload: dict[str, Any]) -> Observation:
        order_id = required_string(payload, "id")
        status = payload.get("status") or payload.get("financial_status")
        if not isinstance(status, str) or not status:
            raise ValueError("Shopify order payload requires status or financial_status")
        return Observation(
            observation_id=f"obs_shopify_{observation_token(order_id)}",
            connector=self.name,
            object_type="order",
            object_id=order_id,
            observed_at=observed_at(payload),
            payload={
                "id": order_id,
                "status": status,
                **({"currency": payload["currency"]} if "currency" in payload else {}),
            },
        )
