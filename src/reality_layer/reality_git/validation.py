from collections.abc import Sequence

from reality_layer.actions.models import ActionEventRecord
from reality_layer.reality_git.hashing import hash_json
from reality_layer.world_state.models import CommitRecord


def validate_commit_chain(commits: Sequence[CommitRecord]) -> None:
    """Raise ValueError when commit links or commit contents have been altered."""
    previous_hash: str | None = None
    for commit in commits:
        if commit.previous_hash != previous_hash:
            raise ValueError(f"Commit chain link mismatch at {commit.commit_id}.")
        expected_hash = hash_json(
            {
                "commit_id": commit.commit_id,
                "tenant_id": commit.tenant_id,
                "parent_commit_id": commit.parent_commit_id,
                "entity_type": commit.entity_type,
                "entity_id": commit.entity_id,
                "cause": commit.cause,
                "observation_ids": commit.observation_ids,
                "before": commit.before,
                "after": commit.after,
                "semantic_diff": commit.semantic_diff,
                "previous_hash": commit.previous_hash,
            }
        )
        if commit.hash != expected_hash:
            raise ValueError(f"Commit hash mismatch at {commit.commit_id}.")
        previous_hash = commit.hash


def validate_event_chain(events: Sequence[ActionEventRecord]) -> None:
    """Raise ValueError when action-event links or event contents have been altered."""
    previous_hash: str | None = None
    for event in events:
        if event.previous_event_hash != previous_hash:
            raise ValueError(f"Event chain link mismatch at {event.event_id}.")
        expected_hash = hash_json(
            {
                "event_id": event.event_id,
                "tenant_id": event.tenant_id,
                "action_id": event.action_id,
                "event_type": event.event_type,
                "actor_role": event.actor_role,
                "payload": event.payload,
                "previous_event_hash": event.previous_event_hash,
            }
        )
        if event.event_hash != expected_hash:
            raise ValueError(f"Event hash mismatch at {event.event_id}.")
        previous_hash = event.event_hash
