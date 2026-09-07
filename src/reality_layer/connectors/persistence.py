from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from reality_layer.connectors.observe import ObservedPayload
from reality_layer.db.models import ObservationLog
from reality_layer.db.repositories import ObservationRepository


@dataclass(frozen=True)
class PersistedObservation:
    observation_id: str
    created: bool


class ObservationIngestionService:
    def __init__(self, session: Session) -> None:
        self.repository = ObservationRepository(session)

    def persist(
        self,
        tenant_id: str,
        observed: ObservedPayload,
        connector_version: str = "mvp-1",
        schema_version: str = "order-to-cash/1.0.0",
    ) -> PersistedObservation:
        observation = observed.observation
        existing = self.repository.get(tenant_id, observation.observation_id)
        if existing is not None:
            return PersistedObservation(observation.observation_id, False)

        row = ObservationLog(
            tenant_id=tenant_id,
            observation_id=observation.observation_id,
            connector_id=observation.connector,
            external_object_type=observation.object_type,
            external_object_id=observation.object_id,
            external_event_id=observation.observation_id,
            source_timestamp=observation.observed_at,
            observed_at=observation.observed_at,
            payload_hash=observed.raw_payload.payload_hash,
            payload_ref=observed.raw_payload.ref,
            connector_version=connector_version,
            schema_version=schema_version,
            correlation_id=f"cor_{uuid4().hex[:16]}",
            ingest_outcome="accepted",
        )
        self.repository.add(row)
        return PersistedObservation(observation.observation_id, True)
