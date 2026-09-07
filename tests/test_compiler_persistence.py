from datetime import UTC, datetime

from reality_layer.connectors import ShopifyConnector
from reality_layer.connectors.observe import observe_payload
from reality_layer.db.models import CommitLog, StateProjection
from reality_layer.storage import LocalObjectStore
from reality_layer.world_state import CompilerPersistenceService, WorldStateService


def test_compiler_persistence_maps_commit_and_projection(tmp_path, monkeypatch) -> None:
    state_service = WorldStateService()
    observed = observe_payload(
        "tenant_a",
        {"id": "123", "status": "open", "updated_at": datetime.now(UTC).isoformat()},
        ShopifyConnector(),
        LocalObjectStore(tmp_path),
    )
    state = state_service.ingest("tenant_a", observed.observation)
    commit = state_service.get_commit_for_state("tenant_a", state)
    commits: list[CommitLog] = []
    projections: list[StateProjection] = []

    class FakeCommitRepository:
        def __init__(self, session) -> None:
            pass

        def add(self, row: CommitLog) -> CommitLog:
            commits.append(row)
            return row

        def get(self, tenant_id: str, commit_id: str) -> CommitLog | None:
            return None

    class FakeProjectionRepository:
        def __init__(self, session) -> None:
            pass

        def save(self, row: StateProjection) -> StateProjection:
            projections.append(row)
            return row

    monkeypatch.setattr(
        "reality_layer.world_state.persistence.CommitRepository", FakeCommitRepository
    )
    monkeypatch.setattr(
        "reality_layer.world_state.persistence.StateProjectionRepository",
        FakeProjectionRepository,
    )

    CompilerPersistenceService(None).persist(state, commit)  # type: ignore[arg-type]

    assert commits[0].hash == commit.hash
    assert projections[0].producing_commit_id == commit.commit_id
    assert projections[0].tenant_id == "tenant_a"
