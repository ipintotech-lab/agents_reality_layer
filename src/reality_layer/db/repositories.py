from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from reality_layer.db.models import ActionEvent, CommitLog, ObservationLog, StateProjection


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

    def list_for_tenant(
        self, tenant_id: str, entity_type: str | None = None
    ) -> Sequence[StateProjection]:
        statement = tenant_select(StateProjection, tenant_id)
        if entity_type is not None:
            statement = statement.where(StateProjection.entity_type == entity_type)
        return self.session.scalars(statement.order_by(StateProjection.entity_id.asc())).all()

    def save(self, projection: StateProjection) -> StateProjection:
        existing = self.get(projection.tenant_id, projection.entity_id)
        if existing is not None:
            for column in (
                "entity_type",
                "attributes",
                "confidence",
                "freshness",
                "provenance",
                "producing_commit_id",
                "state_version",
            ):
                setattr(existing, column, getattr(projection, column))
            projection = existing
        else:
            self.session.add(projection)
        self.session.flush()
        return projection


class CommitRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, commit: CommitLog) -> CommitLog:
        self.session.add(commit)
        self.session.flush()
        return commit

    def get(self, tenant_id: str, commit_id: str) -> CommitLog | None:
        return self.session.scalars(
            tenant_get_by_id(CommitLog, tenant_id, "commit_id", commit_id)
        ).first()

    def list_for_tenant(self, tenant_id: str) -> Sequence[CommitLog]:
        statement = tenant_select(CommitLog, tenant_id).order_by(
            CommitLog.created_at.asc(), CommitLog.commit_id.asc()
        )
        return self.session.scalars(statement).all()

    def latest(self, tenant_id: str) -> CommitLog | None:
        statement = (
            tenant_select(CommitLog, tenant_id)
            .order_by(CommitLog.created_at.desc())
            .limit(1)
        )
        return self.session.scalars(statement).first()


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

    def list_for_tenant(self, tenant_id: str) -> Sequence[ActionEvent]:
        return self.session.scalars(tenant_select(ActionEvent, tenant_id)).all()

    def distinct_tenants(self) -> Sequence[str]:
        return self.session.scalars(select(ActionEvent.tenant_id).distinct()).all()
