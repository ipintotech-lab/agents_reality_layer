import json
from dataclasses import dataclass
from typing import Any, Protocol

from reality_layer.storage import ObjectStore, StoredObject
from reality_layer.world_state.models import Observation


class Normalizer(Protocol):
    def normalize(self, payload: dict[str, Any]) -> Observation:
        ...


@dataclass(frozen=True)
class ObservedPayload:
    observation: Observation
    raw_payload: StoredObject


def observe_payload(
    tenant_id: str,
    payload: dict[str, Any],
    normalizer: Normalizer,
    object_store: ObjectStore,
) -> ObservedPayload:
    observation = normalizer.normalize(payload)
    raw_payload = object_store.put_raw_payload(
        tenant_id,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        "application/json",
    )
    return ObservedPayload(observation, raw_payload)
