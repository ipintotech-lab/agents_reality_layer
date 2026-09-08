from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from reality_layer.reality_git import hash_json
from reality_layer.world_state.models import CommitRecord, Observation, OrderState, StateAttribute


class WorldStateService:
    def __init__(self) -> None:
        self._observations: dict[tuple[str, str], Observation] = {}
        self._states: dict[tuple[str, str, str], OrderState] = {}
        self._commits: dict[tuple[str, str], CommitRecord] = {}
        self._latest_commit: dict[str, str] = {}

    def ingest(
        self,
        tenant_id: str,
        observation: Observation,
        cause: str = "observation",
        assurance_level: str = "observed",
    ) -> OrderState:
        key = (tenant_id, observation.observation_id)
        if key in self._observations:
            return self._states[(tenant_id, observation.object_type, observation.object_id)]

        self._observations[key] = observation
        state_key = (tenant_id, observation.object_type, observation.object_id)
        previous = self._states.get(state_key)
        attributes = self._project(observation)
        before = self._attributes_for(previous)
        after = {name: attribute.model_dump(mode="json") for name, attribute in attributes.items()}
        semantic_diff = self._diff(before, after)
        if previous is not None and not semantic_diff["attributes_changed"]:
            return previous
        parent_commit_id = self._latest_commit.get(tenant_id)
        commit_id = f"cmt_{uuid4().hex[:16]}"
        previous_hash = self._latest_hash(tenant_id)
        commit_hash = hash_json(
            {
                "commit_id": commit_id,
                "tenant_id": tenant_id,
                "parent_commit_id": parent_commit_id,
                "entity_type": observation.object_type,
                "entity_id": observation.object_id,
                "cause": cause,
                "observation_ids": [observation.observation_id],
                "before": before,
                "after": after,
                "semantic_diff": semantic_diff,
                "previous_hash": previous_hash,
            }
        )
        commit = CommitRecord(
            commit_id=commit_id,
            tenant_id=tenant_id,
            parent_commit_id=parent_commit_id,
            entity_type=observation.object_type,
            entity_id=observation.object_id,
            cause=cause,
            observation_ids=[observation.observation_id],
            before=before,
            after=after,
            semantic_diff=semantic_diff,
            assurance_level=assurance_level,
            previous_hash=previous_hash,
            hash=commit_hash,
        )
        self._commits[(tenant_id, commit_id)] = commit
        self._latest_commit[tenant_id] = commit_id
        state = OrderState(
            tenant_id=tenant_id,
            entity_id=f"{observation.object_type}:{observation.object_id}",
            entity_type=observation.object_type.capitalize(),
            state_version=(previous.state_version + 1) if previous else 1,
            attributes=attributes,
            commit_id=commit_id,
        )
        self._states[state_key] = state
        return state

    def hydrate(
        self,
        state: OrderState,
        parent_commit_id: str | None = None,
        parent_hash: str | None = None,
    ) -> None:
        key = (state.tenant_id, state.entity_type.lower(), state.entity_id.split(":", 1)[-1])
        self._states[key] = state
        self._latest_commit[state.tenant_id] = parent_commit_id or state.commit_id
        if parent_commit_id and parent_hash:
            self._commits[(state.tenant_id, parent_commit_id)] = CommitRecord(
                commit_id=parent_commit_id,
                tenant_id=state.tenant_id,
                entity_type=state.entity_type.lower(),
                entity_id=state.entity_id.split(":", 1)[-1],
                cause="hydrated",
                observation_ids=[],
                before={},
                after={},
                semantic_diff={"attributes_changed": []},
                assurance_level="observed",
                hash=parent_hash,
            )

    def get_order(self, tenant_id: str, order_id: str) -> OrderState:
        return self.get_entity(tenant_id, "order", order_id)

    def get_entity(self, tenant_id: str, entity_type: str, entity_id: str) -> OrderState:
        try:
            return self._states[(tenant_id, entity_type, entity_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown {entity_type}: {entity_id}") from exc

    def list_entities(
        self, tenant_id: str, entity_type: str | None = None
    ) -> list[OrderState]:
        states = [
            state
            for (state_tenant, state_type, _), state in self._states.items()
            if state_tenant == tenant_id
            and (entity_type is None or state_type == entity_type.lower())
        ]
        return sorted(states, key=lambda state: state.entity_id)

    def get_commit(self, tenant_id: str, commit_id: str) -> CommitRecord:
        try:
            return self._commits[(tenant_id, commit_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown commit: {commit_id}") from exc

    def get_commit_for_state(self, tenant_id: str, state: OrderState) -> CommitRecord:
        return self.get_commit(tenant_id, state.commit_id)

    def list_commits(
        self, tenant_id: str, since_commit_id: str | None = None
    ) -> list[CommitRecord]:
        commits = [
            commit
            for (commit_tenant, _), commit in self._commits.items()
            if commit_tenant == tenant_id
        ]
        commits.sort(key=lambda commit: commit.commit_id)
        if since_commit_id is not None:
            for index, commit in enumerate(commits):
                if commit.commit_id == since_commit_id:
                    return commits[index + 1 :]
            raise KeyError(f"Unknown commit: {since_commit_id}")
        return commits

    def _latest_hash(self, tenant_id: str) -> str | None:
        commit_id = self._latest_commit.get(tenant_id)
        return self._commits[(tenant_id, commit_id)].hash if commit_id else None

    @staticmethod
    def _attributes_for(state: OrderState | None) -> dict[str, object]:
        if state is None:
            return {}
        return {
            name: attribute.model_dump(mode="json")
            for name, attribute in state.attributes.items()
        }

    @staticmethod
    def _diff(
        before: Mapping[str, object], after: Mapping[str, object]
    ) -> dict[str, object]:
        changed = sorted(
            name
            for name in set(before) | set(after)
            if WorldStateService._attribute_value(before.get(name))
            != WorldStateService._attribute_value(after.get(name))
        )
        return {"attributes_changed": changed}

    @staticmethod
    def _attribute_value(attribute: object) -> object:
        if isinstance(attribute, dict):
            return attribute.get("value")
        return attribute

    def _project(self, observation: Observation) -> dict[str, StateAttribute]:
        now = datetime.now(UTC)
        freshness = "fresh" if now - observation.observed_at <= timedelta(minutes=5) else "stale"
        return {
            name: StateAttribute(
                value=value,
                confidence=0.98 if name in {"id", "status"} else 0.9,
                observed_at=observation.observed_at,
                freshness=freshness,
                source_observation_ids=[observation.observation_id],
            )
            for name, value in observation.payload.items()
        }
