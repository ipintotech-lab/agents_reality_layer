from datetime import UTC, datetime

from fastapi.testclient import TestClient

from reality_layer.api.app import create_app


def _observation(observation_id: str, object_id: str, status: str) -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "connector": "shopify",
        "object_type": "order",
        "object_id": object_id,
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {"id": object_id, "status": status},
    }


def test_action_status_and_diff_endpoints_are_registered() -> None:
    client = TestClient(create_app())

    assert client.get("/v1/actions/missing").status_code == 404
    assert client.get("/v1/diffs").status_code == 200
    assert client.get("/v1/diffs").json() == []
    assert client.get("/v1/connectors").json() == []


def test_diff_history_is_chronological_and_cursor_aware() -> None:
    client = TestClient(create_app())

    first = client.post(
        "/v1/observations",
        json=_observation("obs_diff_1", "order-1", "open"),
        headers={"X-Reality-Tenant": "tenant-diff"},
    )
    second = client.post(
        "/v1/observations",
        json=_observation("obs_diff_2", "order-1", "paid"),
        headers={"X-Reality-Tenant": "tenant-diff"},
    )

    first_commit_id = first.json()["commit_id"]
    second_commit_id = second.json()["commit_id"]

    diffs = client.get("/v1/diffs", headers={"X-Reality-Tenant": "tenant-diff"})
    assert [item["commit_id"] for item in diffs.json()] == [
        first_commit_id,
        second_commit_id,
    ]

    later = client.get(
        "/v1/diffs",
        params={"since_commit": first_commit_id},
        headers={"X-Reality-Tenant": "tenant-diff"},
    )
    assert [item["commit_id"] for item in later.json()] == [second_commit_id]
