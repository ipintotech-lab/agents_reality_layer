from fastapi.testclient import TestClient

from reality_layer.api.app import create_app


def test_workspace_view_reports_the_configured_mode_without_persistence() -> None:
    client = TestClient(create_app())

    body = client.get("/v1/workspace").json()

    assert body["mode"] == "demo_proposal"
    assert body["persistent"] is False


def test_setting_mode_without_persistence_is_rejected() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/workspace/mode",
        json={"mode": "observe_only"},
        headers={"X-Reality-Role": "operations"},
    )

    assert response.status_code == 409


def test_setting_mode_requires_a_privileged_role() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/workspace/mode",
        json={"mode": "observe_only"},
        headers={"X-Reality-Role": "observer"},
    )

    assert response.status_code == 403


def test_unknown_mode_is_rejected_by_schema() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/workspace/mode",
        json={"mode": "wide_open"},
        headers={"X-Reality-Role": "admin"},
    )

    assert response.status_code == 422
