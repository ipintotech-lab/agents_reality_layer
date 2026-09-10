from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from reality_layer.reality_git import hash_json
from reality_layer.world_state.models import (
    CommitRecord,
    Conflict,
    ConflictCandidate,
    Observation,
    OrderState,
    StateAttribute,
)


class WorldStateService:
    def __init__(self) -> None:
        self._observations: dict[tuple[str, str], Observation] = {}
        self._states: dict[tuple[str, str, str], OrderState] = {}
        self._commits: dict[tuple[str, str], CommitRecord] = {}
        self._latest_commit: dict[str, str] = {}
        self._open_conflicts: dict[tuple[str, str, str, str], Conflict] = {}
        self._conflicts_by_id: dict[tuple[str, str], Conflict] = {}

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
        previous_attributes = previous.attributes if previous else {}
        incoming_attributes = self._project(observation)

        attributes = dict(previous_attributes)
        for name, incoming in incoming_attributes.items():
            existing = previous_attributes.get(name)
            if (
                existing is not None
                and existing.value != incoming.value
                and existing.freshness == "fresh"
                and existing.connector is not None
                and existing.connector != incoming.connector
            ):
                self._record_conflict(
                    tenant_id,
                    observation.object_type,
                    observation.object_id,
                    name,
                    existing,
                    incoming,
                )
                continue
            attributes[name] = incoming

        before = self._attributes_for(previous)
        after = {name: attribute.model_dump(mode="json") for name, attribute in attributes.items()}
        semantic_diff = self._diff(before, after)
        if previous is not None and not semantic_diff["attributes_changed"]:
            return previous

        commit = self._create_commit(
            tenant_id=tenant_id,
            entity_type=observation.object_type,
            entity_id=observation.object_id,
            cause=cause,
            observation_ids=[observation.observation_id],
            before=before,
            after=after,
            semantic_diff=semantic_diff,
            assurance_level=assurance_level,
        )
        state = OrderState(
            tenant_id=tenant_id,
            entity_id=f"{observation.object_type}:{observation.object_id}",
            entity_type=observation.object_type.capitalize(),
            state_version=(previous.state_version + 1) if previous else 1,
            attributes=attributes,
            commit_id=commit.commit_id,
        )
        self._states[state_key] = state
        return state

    def _create_commit(
        self,
        *,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        cause: str,
        observation_ids: list[str],
        before: Mapping[str, object],
        after: Mapping[str, object],
        semantic_diff: dict[str, object],
        assurance_level: str,
    ) -> CommitRecord:
        parent_commit_id = self._latest_commit.get(tenant_id)
        commit_id = f"cmt_{uuid4().hex[:16]}"
        previous_hash = self._latest_hash(tenant_id)
        commit_hash = hash_json(
            {
                "commit_id": commit_id,
                "tenant_id": tenant_id,
                "parent_commit_id": parent_commit_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "cause": cause,
                "observation_ids": observation_ids,
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
            entity_type=entity_type,
            entity_id=entity_id,
            cause=cause,
            observation_ids=observation_ids,
            before=dict(before),
            after=dict(after),
            semantic_diff=semantic_diff,
            assurance_level=assurance_level,
            previous_hash=previous_hash,
            hash=commit_hash,
        )
        self._commits[(tenant_id, commit_id)] = commit
        self._latest_commit[tenant_id] = commit_id
        return commit

    @staticmethod
    def _last_observation_id(attribute: StateAttribute) -> str | None:
        return attribute.source_observation_ids[-1] if attribute.source_observation_ids else None

    def _record_conflict(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        attribute: str,
        existing: StateAttribute,
        incoming: StateAttribute,
    ) -> Conflict:
        conflict_key = (tenant_id, entity_type, entity_id, attribute)
        open_conflict = self._open_conflicts.get(conflict_key)
        incoming_candidate = ConflictCandidate(
            value=incoming.value,
            connector=incoming.connector,
            observation_id=self._last_observation_id(incoming),
            observed_at=incoming.observed_at,
            confidence=incoming.confidence,
        )
        if open_conflict is not None:
            already_seen = any(
                candidate.connector == incoming_candidate.connector
                and candidate.value == incoming_candidate.value
                for candidate in open_conflict.candidates
            )
            if not already_seen:
                open_conflict.candidates.append(incoming_candidate)
            return open_conflict

        existing_candidate = ConflictCandidate(
            value=existing.value,
            connector=existing.connector,
            observation_id=self._last_observation_id(existing),
            observed_at=existing.observed_at,
            confidence=existing.confidence,
        )
        conflict = Conflict(
            conflict_id=f"cnf_{uuid4().hex[:16]}",
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            attribute=attribute,
            candidates=[existing_candidate, incoming_candidate],
            detected_at=datetime.now(UTC),
        )
        self._open_conflicts[conflict_key] = conflict
        self._conflicts_by_id[(tenant_id, conflict.conflict_id)] = conflict
        return conflict

    def has_open_conflicts(self, tenant_id: str, entity_type: str, entity_id: str) -> bool:
        return any(
            key[0] == tenant_id and key[1] == entity_type and key[2] == entity_id
            for key in self._open_conflicts
        )

    def get_conflict(self, tenant_id: str, conflict_id: str) -> Conflict:
        try:
            return self._conflicts_by_id[(tenant_id, conflict_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown conflict: {conflict_id}") from exc

    def list_conflicts(self, tenant_id: str, status: str | None = None) -> list[Conflict]:
        conflicts = [
            conflict
            for (conflict_tenant, _), conflict in self._conflicts_by_id.items()
            if conflict_tenant == tenant_id and (status is None or conflict.status == status)
        ]
        return sorted(conflicts, key=lambda conflict: conflict.detected_at)

    def resolve_conflict(
        self,
        tenant_id: str,
        conflict_id: str,
        resolved_value: object,
        resolved_by: str,
        reason: str,
    ) -> Conflict:
        conflict = self.get_conflict(tenant_id, conflict_id)
        if conflict.status == "resolved":
            return conflict

        now = datetime.now(UTC)
        matching = [
            candidate for candidate in conflict.candidates if candidate.value == resolved_value
        ]
        source_observation_ids = [
            candidate.observation_id for candidate in matching if candidate.observation_id
        ] or [
            candidate.observation_id
            for candidate in conflict.candidates
            if candidate.observation_id
        ]
        confidence = max((candidate.confidence for candidate in matching), default=0.95)

        state_key = (tenant_id, conflict.entity_type, conflict.entity_id)
        state = self._states.get(state_key)
        if state is not None:
            before = self._attributes_for(state)
            resolved_attribute = StateAttribute(
                value=resolved_value,
                confidence=confidence,
                observed_at=now,
                freshness="fresh",
                source_observation_ids=source_observation_ids,
                connector="operator",
            )
            attributes = dict(state.attributes)
            attributes[conflict.attribute] = resolved_attribute
            after = {
                name: attribute.model_dump(mode="json") for name, attribute in attributes.items()
            }
            semantic_diff = self._diff(before, after)
            commit = self._create_commit(
                tenant_id=tenant_id,
                entity_type=conflict.entity_type,
                entity_id=conflict.entity_id,
                cause=f"conflict_resolved:{conflict.conflict_id}",
                observation_ids=[oid for oid in source_observation_ids if oid],
                before=before,
                after=after,
                semantic_diff=semantic_diff,
                assurance_level="operator_resolved",
            )
            self._states[state_key] = OrderState(
                tenant_id=tenant_id,
                entity_id=state.entity_id,
                entity_type=state.entity_type,
                state_version=state.state_version + 1,
                attributes=attributes,
                commit_id=commit.commit_id,
            )

        conflict.status = "resolved"
        conflict.resolved_value = resolved_value
        conflict.resolved_by = resolved_by
        conflict.resolved_at = now
        conflict.resolution_reason = reason
        conflict_key = (tenant_id, conflict.entity_type, conflict.entity_id, conflict.attribute)
        self._open_conflicts.pop(conflict_key, None)
        return conflict

    def hydrate(
        self,
        state: OrderState,
        parent_commit_id: str | None = None,
        parent_hash: str | None = None,
    ) -> None:
        key = (state.tenant_id, state.entity_type.lower(), state.entity_id.split(":", 1)[-1])
        self._states[key] = state

        current_latest = self._latest_commit.get(state.tenant_id)
        if current_latest is None:
            self._latest_commit[state.tenant_id] = parent_commit_id or state.commit_id
        elif self._is_ancestor(state.tenant_id, state.commit_id, current_latest):
            self._latest_commit[state.tenant_id] = current_latest
        else:
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
        self,
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[OrderState]:
        states = [
            state_record
            for (state_tenant, state_type, _), state_record in self._states.items()
            if state_tenant == tenant_id
            and (entity_type is None or state_type == entity_type.lower())
            and self._matches_filters(
                state_record, state, freshness, min_confidence
            )
        ]
        return sorted(states, key=lambda state: state.entity_id)

    @staticmethod
    def _matches_filters(
        entity: OrderState,
        state_filter: str | None,
        freshness_filter: str | None,
        min_confidence: float | None,
    ) -> bool:
        attributes = entity.attributes.values()
        if state_filter is not None and not any(
            str(attribute.value) == state_filter for attribute in attributes
        ):
            return False
        if freshness_filter is not None and not any(
            attribute.freshness == freshness_filter for attribute in attributes
        ):
            return False
        if min_confidence is not None and not any(
            attribute.confidence >= min_confidence for attribute in attributes
        ):
            return False
        return True

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
        latest_commit_id = self._latest_commit.get(tenant_id)
        if latest_commit_id is None:
            return []

        commits: list[CommitRecord] = []
        seen: set[str] = set()
        current_commit_id: str | None = latest_commit_id
        while current_commit_id is not None and current_commit_id not in seen:
            commit = self._commits.get((tenant_id, current_commit_id))
            if commit is None:
                break
            commits.append(commit)
            seen.add(current_commit_id)
            current_commit_id = commit.parent_commit_id
        commits.reverse()

        if since_commit_id is not None:
            for index, commit in enumerate(commits):
                if commit.commit_id == since_commit_id:
                    return commits[index + 1 :]
            raise KeyError(f"Unknown commit: {since_commit_id}")
        return commits

    def _is_ancestor(
        self, tenant_id: str, candidate_commit_id: str, descendant_commit_id: str
    ) -> bool:
        current_commit_id: str | None = descendant_commit_id
        seen: set[str] = set()
        while current_commit_id is not None and current_commit_id not in seen:
            if current_commit_id == candidate_commit_id:
                return True
            seen.add(current_commit_id)
            current_commit = self._commits.get((tenant_id, current_commit_id))
            if current_commit is None:
                break
            current_commit_id = current_commit.parent_commit_id
        return False

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
                connector=observation.connector,
            )
            for name, value in observation.payload.items()
        }
