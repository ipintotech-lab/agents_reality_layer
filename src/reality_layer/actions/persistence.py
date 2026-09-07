from sqlalchemy.orm import Session

from reality_layer.actions.models import ActionEventRecord
from reality_layer.db.models import ActionEvent
from reality_layer.db.repositories import ActionEventRepository


class ActionEventPersistenceService:
    def __init__(self, session: Session) -> None:
        self.repository = ActionEventRepository(session)

    def persist(self, event: ActionEventRecord) -> None:
        existing = self.repository.session.get(ActionEvent, (event.tenant_id, event.event_id))
        if existing is not None:
            return
        self.repository.append(
            ActionEvent(
                tenant_id=event.tenant_id,
                event_id=event.event_id,
                action_id=event.action_id,
                event_type=event.event_type,
                schema_version="actions/1.0.0",
                actor={"type": "role", "id": event.actor_role},
                correlation_id=event.action_id,
                payload=event.payload,
                evidence_refs=[],
                previous_event_hash=event.previous_event_hash,
                event_hash=event.event_hash,
            )
        )

    def list_for_action(self, tenant_id: str, action_id: str) -> list[ActionEventRecord]:
        return [
            ActionEventRecord(
                event_id=row.event_id,
                tenant_id=row.tenant_id,
                action_id=row.action_id,
                event_type=row.event_type,
                actor_role=str(row.actor.get("id", "system")),
                payload=row.payload,
                previous_event_hash=row.previous_event_hash,
                event_hash=row.event_hash,
            )
            for row in self.repository.list_for_action(tenant_id, action_id)
        ]

    def list_for_tenant(self, tenant_id: str) -> list[ActionEventRecord]:
        rows = self.repository.list_for_tenant(tenant_id)
        return [
            ActionEventRecord(
                event_id=row.event_id,
                tenant_id=row.tenant_id,
                action_id=row.action_id,
                event_type=row.event_type,
                actor_role=str(row.actor.get("id", "system")),
                payload=row.payload,
                previous_event_hash=row.previous_event_hash,
                event_hash=row.event_hash,
            )
            for row in rows
        ]
