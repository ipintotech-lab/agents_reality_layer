from sqlalchemy.orm import Session

from reality_layer.db.models import CommitLog, ConflictRecord, StateProjection
from reality_layer.db.repositories import (
    CommitRepository,
    ConflictRepository,
    StateProjectionRepository,
)
from reality_layer.world_state.models import (
    CommitRecord,
    Conflict,
    ConflictCandidate,
    OrderState,
    StateAttribute,
)
from reality_layer.world_state.service import WorldStateService


class CompilerPersistenceService:
    def __init__(self, session: Session) -> None:
        self.projections = StateProjectionRepository(session)
        self.commits = CommitRepository(session)
        self.conflicts = ConflictRepository(session)

    def persist(self, state: OrderState, commit: CommitRecord) -> None:
        if self.commits.get(commit.tenant_id, commit.commit_id) is not None:
            return
        self.commits.add(
            CommitLog(
                tenant_id=commit.tenant_id,
                commit_id=commit.commit_id,
                parent_commit_id=commit.parent_commit_id,
                entity_type=commit.entity_type,
                entity_id=commit.entity_id,
                actor={"type": "system", "id": "reality-compiler"},
                cause=commit.cause,
                observation_ids=commit.observation_ids,
                action_id=None,
                mapping_version="mvp-1",
                before=commit.before,
                after=commit.after,
                semantic_diff=commit.semantic_diff,
                assurance_level=commit.assurance_level,
                previous_hash=commit.previous_hash,
                hash=commit.hash,
            )
        )
        self.projections.save(
            StateProjection(
                tenant_id=state.tenant_id,
                entity_id=state.entity_id,
                entity_type=state.entity_type,
                attributes={
                    name: attribute.model_dump(mode="json")
                    for name, attribute in state.attributes.items()
                },
                confidence={
                    name: attribute.confidence for name, attribute in state.attributes.items()
                },
                freshness={
                    name: attribute.freshness for name, attribute in state.attributes.items()
                },
                provenance=[
                    observation_id
                    for attribute in state.attributes.values()
                    for observation_id in attribute.source_observation_ids
                ],
                producing_commit_id=state.commit_id,
                state_version=state.state_version,
            )
        )

    def load_state(self, tenant_id: str, entity_id: str) -> OrderState | None:
        row = self.projections.get(tenant_id, entity_id)
        if row is None:
            return None
        attributes = {
            name: StateAttribute.model_validate(attribute)
            for name, attribute in row.attributes.items()
        }
        return OrderState(
            tenant_id=tenant_id,
            entity_id=row.entity_id,
            entity_type=row.entity_type,
            state_version=row.state_version,
            attributes=attributes,
            commit_id=row.producing_commit_id or "",
        )

    def list_states(
        self,
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[OrderState]:
        rows = self.projections.list_for_tenant(tenant_id, entity_type)
        states = [
            OrderState(
                tenant_id=tenant_id,
                entity_id=row.entity_id,
                entity_type=row.entity_type,
                state_version=row.state_version,
                attributes={
                    name: StateAttribute.model_validate(attribute)
                    for name, attribute in row.attributes.items()
                },
                commit_id=row.producing_commit_id or "",
            )
            for row in rows
        ]
        return [
            state_record
            for state_record in states
            if WorldStateService._matches_filters(
                state_record, state, freshness, min_confidence
            )
        ]

    def persist_conflict(self, conflict: Conflict) -> None:
        self.conflicts.save(
            ConflictRecord(
                tenant_id=conflict.tenant_id,
                conflict_id=conflict.conflict_id,
                entity_type=conflict.entity_type,
                entity_id=conflict.entity_id,
                attribute=conflict.attribute,
                candidates=[
                    candidate.model_dump(mode="json") for candidate in conflict.candidates
                ],
                status=conflict.status,
                detected_at=conflict.detected_at,
                resolved_value=conflict.resolved_value,
                resolved_by=conflict.resolved_by,
                resolved_at=conflict.resolved_at,
                resolution_reason=conflict.resolution_reason,
            )
        )

    @staticmethod
    def _to_conflict(row: ConflictRecord) -> Conflict:
        return Conflict(
            conflict_id=row.conflict_id,
            tenant_id=row.tenant_id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            attribute=row.attribute,
            candidates=[
                ConflictCandidate.model_validate(candidate) for candidate in row.candidates
            ],
            status=row.status,
            detected_at=row.detected_at,
            resolved_value=row.resolved_value,
            resolved_by=row.resolved_by,
            resolved_at=row.resolved_at,
            resolution_reason=row.resolution_reason,
        )

    def load_conflict(self, tenant_id: str, conflict_id: str) -> Conflict | None:
        row = self.conflicts.get(tenant_id, conflict_id)
        return self._to_conflict(row) if row is not None else None

    def list_conflicts(self, tenant_id: str, status: str | None = None) -> list[Conflict]:
        return [
            self._to_conflict(row)
            for row in self.conflicts.list_for_tenant(tenant_id, status)
        ]

    def has_open_conflict_for_entity(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> bool:
        return bool(
            self.conflicts.list_open_for_entity(tenant_id, entity_type, entity_id)
        )

    def load_commit(self, tenant_id: str, commit_id: str) -> CommitRecord | None:
        row = self.commits.get(tenant_id, commit_id)
        if row is None:
            return None
        return CommitRecord(
            commit_id=row.commit_id,
            tenant_id=row.tenant_id,
            parent_commit_id=row.parent_commit_id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            cause=row.cause,
            observation_ids=list(row.observation_ids),
            before=row.before,
            after=row.after,
            semantic_diff=row.semantic_diff,
            assurance_level=row.assurance_level,
            previous_hash=row.previous_hash,
            hash=row.hash,
        )

    def list_commits(
        self, tenant_id: str, since_commit_id: str | None = None
    ) -> list[CommitRecord]:
        rows = self.commits.list_for_tenant(tenant_id)
        commits = [
            CommitRecord(
                commit_id=row.commit_id,
                tenant_id=row.tenant_id,
                parent_commit_id=row.parent_commit_id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                cause=row.cause,
                observation_ids=list(row.observation_ids),
                before=row.before,
                after=row.after,
                semantic_diff=row.semantic_diff,
                assurance_level=row.assurance_level,
                previous_hash=row.previous_hash,
                hash=row.hash,
            )
            for row in rows
        ]
        if since_commit_id is not None:
            for index, commit in enumerate(commits):
                if commit.commit_id == since_commit_id:
                    return commits[index + 1 :]
            raise KeyError(f"Unknown commit: {since_commit_id}")
        return commits
