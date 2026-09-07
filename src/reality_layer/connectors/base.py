import re
from datetime import UTC, datetime
from typing import Any, Protocol

from reality_layer.world_state.models import Observation


class Connector(Protocol):
    name: str

    def normalize(self, payload: dict[str, Any]) -> Observation:
        ...


def required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Connector payload requires non-empty string field: {field}")
    return value


def observation_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def observed_at(payload: dict[str, Any]) -> datetime:
    value = payload.get("updated_at") or payload.get("created_at")
    if value is None:
        return datetime.now(UTC)
    if not isinstance(value, str):
        raise ValueError("Connector timestamp must be an ISO-8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
