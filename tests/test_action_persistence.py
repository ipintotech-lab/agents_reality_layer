from reality_layer.actions.models import ActionEventRecord
from reality_layer.actions.persistence import ActionEventPersistenceService


def test_action_event_persistence_maps_append_only_event(monkeypatch) -> None:
    rows = []

    class FakeRepository:
        def __init__(self, session) -> None:
            self.session = self

        def get(self, model, key):
            return None

        def append(self, row):
            rows.append(row)
            return row

    monkeypatch.setattr(
        "reality_layer.actions.persistence.ActionEventRepository", FakeRepository
    )
    event = ActionEventRecord(
        event_id="evt_1",
        tenant_id="tenant_a",
        action_id="act_1",
        event_type="approved",
        actor_role="operations",
        payload={"reason": "ok"},
        event_hash="sha256:event",
    )

    ActionEventPersistenceService(None).persist(event)  # type: ignore[arg-type]

    assert rows[0].tenant_id == "tenant_a"
    assert rows[0].actor["id"] == "operations"
