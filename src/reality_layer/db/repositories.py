from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from reality_layer.db.models import ActionEvent, ObservationLog, StateProjection


def tenant_select(model: Any, tenant_id: str) -> Select[Any]:
    return select(model).where(model.tenant_id == tenant_id)


def tenant_get_by_id(model: Any, tenant_id: str, id_column: str, id_value: Any) -> Select[Any]:
    return tenant_select(model, tenant_id).where(getattr(model, id_column) == id_value)


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: str, observation_id: str) -> ObservationLog | None:
        return self.session.scalars(
            tenant_get_by_id(ObservationLog, tenant_id, "observation_id", observation_id)
        ).first()

    def add(self, observation: ObservationLog) -> ObservationLog:
        self.session.add(observation)
        self.session.flush()
        return observation


class StateProjectionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: str, entity_id: str) -> StateProjection | None:
        return self.session.scalars(
            tenant_get_by_id(StateProjection, tenant_id, "entity_id", entity_id)
        ).first()

    def save(self, projection: StateProjection) -> StateProjection:
        self.session.add(projection)
        self.session.flush()
        return projection


class ActionEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: ActionEvent) -> ActionEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def list_for_action(self, tenant_id: str, action_id: str) -> Sequence[ActionEvent]:
        statement = tenant_select(ActionEvent, tenant_id).where(ActionEvent.action_id == action_id)
        return self.session.scalars(statement).all()
