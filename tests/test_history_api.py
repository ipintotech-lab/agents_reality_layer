from fastapi.testclient import TestClient

from reality_layer.api.app import create_app


def test_action_status_and_diff_endpoints_are_registered() -> None:
    client = TestClient(create_app())

    assert client.get("/v1/actions/missing").status_code == 404
    assert client.get("/v1/diffs").status_code == 200
    assert client.get("/v1/diffs").json() == []
