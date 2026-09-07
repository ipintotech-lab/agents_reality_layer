from typing import Any

from reality_layer.connectors.base import observation_token, observed_at, required_string
from reality_layer.world_state.models import Observation


class ShopifyConnector:
    name = "shopify"

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
