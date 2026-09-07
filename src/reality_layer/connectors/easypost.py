from typing import Any

from reality_layer.connectors.base import observation_token, observed_at, required_string
from reality_layer.world_state.models import Observation


class EasyPostConnector:
    name = "easypost"

    def normalize(self, payload: dict[str, Any]) -> Observation:
        shipment_id = required_string(payload, "id")
        tracking_code = required_string(payload, "tracking_code")
        status = required_string(payload, "status")
        return Observation(
            observation_id=f"obs_easypost_{observation_token(shipment_id)}",
            connector=self.name,
            object_type="shipment",
            object_id=shipment_id,
            observed_at=observed_at(payload),
            payload={
                "id": shipment_id,
                "tracking_code": tracking_code,
                "status": status,
            },
        )
