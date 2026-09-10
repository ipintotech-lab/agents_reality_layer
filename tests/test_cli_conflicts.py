import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from reality_layer import mcp as mcp_module
from reality_layer.cli import app
from reality_layer.mcp import RealityMcpAdapter

runner = CliRunner()


@pytest.fixture
def in_process_adapter(monkeypatch: pytest.MonkeyPatch) -> RealityMcpAdapter:
    adapter = RealityMcpAdapter()

    def _factory(base_url: str | None = None) -> RealityMcpAdapter:
        return adapter

    monkeypatch.setattr(mcp_module, "RealityMcpAdapter", _factory)
    return adapter


def _seed_conflict(adapter: RealityMcpAdapter, tenant: str = "demo") -> None:
    for connector, status in (("carrier-api", "delayed"), ("erp", "shipped")):
        adapter._client.post(
            "/v1/observations",
            json={
                "observation_id": f"obs_{connector}",
                "connector": connector,
                "object_type": "shipment",
                "object_id": "shp-cli-1",
                "observed_at": datetime.now(UTC).isoformat(),
                "payload": {"id": "shp-cli-1", "status": status},
            },
            headers={"X-Reality-Tenant": tenant},
        )


def test_conflicts_list_and_resolve_via_cli(in_process_adapter: RealityMcpAdapter) -> None:
    _seed_conflict(in_process_adapter)

    listed = runner.invoke(app, ["conflicts", "list"])
    assert listed.exit_code == 0
    conflicts = json.loads(listed.stdout)
    assert len(conflicts) == 1
    conflict_id = conflicts[0]["conflict_id"]

    shown = runner.invoke(app, ["conflicts", "show", conflict_id])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["attribute"] == "status"

    resolved = runner.invoke(
        app,
        ["conflicts", "resolve", conflict_id, "--value", "shipped", "--reason", "carrier lagged"],
    )
    assert resolved.exit_code == 0
    assert json.loads(resolved.stdout)["status"] == "resolved"

    after = runner.invoke(app, ["conflicts", "list", "--status", "open"])
    assert json.loads(after.stdout) == []


def test_conflicts_show_unknown_id_exits_nonzero(in_process_adapter: RealityMcpAdapter) -> None:
    result = runner.invoke(app, ["conflicts", "show", "nope"])
    assert result.exit_code == 1
