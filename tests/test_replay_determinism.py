from datetime import UTC, datetime

from reality_layer.world_state import Observation, WorldStateService


def _observations() -> list[Observation]:
    return [
        Observation(
            observation_id="obs_replay_1",
            connector="shopify",
            object_type="order",
            object_id="order-replay",
            observed_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            payload={"id": "order-replay", "status": "open", "currency": "USD"},
        ),
        Observation(
            observation_id="obs_replay_2",
            connector="shopify",
            object_type="order",
            object_id="order-replay",
            observed_at=datetime(2026, 9, 8, 12, 1, tzinfo=UTC),
            payload={"id": "order-replay", "status": "paid", "currency": "USD"},
        ),
    ]


def test_replaying_same_observations_reproduces_projection_and_diffs() -> None:
    first = WorldStateService()
    second = WorldStateService()

    for observation in _observations():
        first.ingest("tenant-replay", observation)
        second.ingest("tenant-replay", observation)

    first_state = first.get_order("tenant-replay", "order-replay")
    second_state = second.get_order("tenant-replay", "order-replay")
    first_commits = first.list_commits("tenant-replay")
    second_commits = second.list_commits("tenant-replay")

    assert first_state.model_copy(update={"commit_id": ""}) == second_state.model_copy(
        update={"commit_id": ""}
    )
    assert [
        (commit.before, commit.after, commit.semantic_diff, commit.observation_ids)
        for commit in first_commits
    ] == [
        (commit.before, commit.after, commit.semantic_diff, commit.observation_ids)
        for commit in second_commits
    ]
