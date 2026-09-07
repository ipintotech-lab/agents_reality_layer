from datetime import UTC, datetime

from reality_layer.connectors import ShopifyConnector
from reality_layer.connectors.observe import observe_payload
from reality_layer.storage import LocalObjectStore
from reality_layer.world_state import CompilerPersistenceService, WorldStateService


def test_persistence_service_round_trips_domain_state(tmp_path, monkeypatch) -> None:
    observed = observe_payload(
        "tenant_a",
        {"id": "123", "status": "open", "updated_at": datetime.now(UTC).isoformat()},
        ShopifyConnector(),
        LocalObjectStore(tmp_path),
    )
    world_state = WorldStateService()
    state = world_state.ingest("tenant_a", observed.observation)
    commit = world_state.get_commit_for_state("tenant_a", state)

    class CommitRepository:
        def __init__(self, session) -> None:
            pass

        def get(self, tenant_id: str, commit_id: str):
            return commit

        def add(self, row):
            return row

    class ProjectionRepository:
        def __init__(self, session) -> None:
            pass

        def get(self, tenant_id: str, entity_id: str):
            return type(
                "Projection",
                (),
                {
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "entity_type": state.entity_type,
                    "attributes": {
                        name: attribute.model_dump(mode="json")
                        for name, attribute in state.attributes.items()
                    },
                    "state_version": state.state_version,
                    "producing_commit_id": state.commit_id,
                },
            )()

        def save(self, row):
            return row

    monkeypatch.setattr(
        "reality_layer.world_state.persistence.CommitRepository", CommitRepository
    )
    monkeypatch.setattr(
        "reality_layer.world_state.persistence.StateProjectionRepository",
        ProjectionRepository,
    )

    service = CompilerPersistenceService(None)  # type: ignore[arg-type]
    loaded = service.load_state("tenant_a", state.entity_id)
    loaded_commit = service.load_commit("tenant_a", commit.commit_id)

    assert loaded == state
    assert loaded_commit == commit
