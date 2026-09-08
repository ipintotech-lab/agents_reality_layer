from sqlalchemy.orm import Session

from reality_layer.db.models import CommitLog, StateProjection
from reality_layer.db.repositories import CommitRepository, StateProjectionRepository
from reality_layer.world_state.models import CommitRecord, OrderState, StateAttribute


class CompilerPersistenceService:
    def __init__(self, session: Session) -> None:
        self.projections = StateProjectionRepository(session)
        self.commits = CommitRepository(session)

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
        self, tenant_id: str, entity_type: str | None = None
    ) -> list[OrderState]:
        rows = self.projections.list_for_tenant(tenant_id, entity_type)
        return [
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
