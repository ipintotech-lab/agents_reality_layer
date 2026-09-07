from datetime import UTC, datetime

from reality_layer.connectors import ShopifyConnector
from reality_layer.connectors.observe import observe_payload
from reality_layer.connectors.persistence import ObservationIngestionService
from reality_layer.db.models import ObservationLog
from reality_layer.storage import LocalObjectStore


class FakeRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], ObservationLog] = {}

    def get(self, tenant_id: str, observation_id: str) -> ObservationLog | None:
        return self.rows.get((tenant_id, observation_id))

    def add(self, row: ObservationLog) -> ObservationLog:
        self.rows[(row.tenant_id, row.observation_id)] = row
        return row


def test_observation_log_primary_key_is_tenant_scoped() -> None:
    assert [column.name for column in ObservationLog.__table__.primary_key.columns] == [
        "tenant_id",
        "observation_id",
    ]


def test_persisted_observation_contains_raw_payload_reference(tmp_path, monkeypatch) -> None:
    observed = observe_payload(
        "tenant_a",
        {"id": "123", "status": "open", "updated_at": datetime.now(UTC).isoformat()},
        ShopifyConnector(),
        LocalObjectStore(tmp_path),
    )
    repository = FakeRepository()
    monkeypatch.setattr(
        "reality_layer.connectors.persistence.ObservationRepository",
        lambda session: repository,
    )
    service = ObservationIngestionService(None)  # type: ignore[arg-type]

    result = service.persist("tenant_a", observed)

    assert result.created
    row = repository.rows[("tenant_a", observed.observation.observation_id)]
    assert row.payload_ref == observed.raw_payload.ref
    assert row.payload_hash == observed.raw_payload.payload_hash
    assert service.persist("tenant_a", observed).created is False
