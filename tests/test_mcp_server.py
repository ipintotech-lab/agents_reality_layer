import asyncio
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import uvicorn

from reality_layer.api.app import create_app
from reality_layer.mcp_server import build_server


def _call(server: object, name: str, arguments: dict[str, object]) -> dict[str, object] | list:
    _content, structured = asyncio.run(server.call_tool(name, arguments))  # type: ignore[attr-defined]
    return structured["result"] if "result" in structured else structured


def test_mcp_server_exposes_the_adapter_tool_contract() -> None:
    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "get_world_state",
        "query_entities",
        "propose_action",
        "get_action_status",
        "get_proof",
        "diff_since",
        "list_conflicts",
        "get_conflict",
        "resolve_conflict",
    }


def test_mcp_server_tools_round_trip_through_the_rest_contract() -> None:
    server = build_server()
    adapter = server.adapter  # type: ignore[attr-defined]

    adapter._client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_mcp_server_1",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "order-mcp-1",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "order-mcp-1", "status": "open"},
        },
        headers={"X-Reality-Tenant": "tenant-mcp-server"},
    )

    state = _call(server, "get_world_state", {"tenant_id": "tenant-mcp-server"})
    assert state[0]["entity_id"] == "order:order-mcp-1"

    decision = _call(
        server,
        "propose_action",
        {
            "proposal": {
                "action_type": "cancel_order",
                "target_entity": "order:order-mcp-1",
                "reason": "Duplicate test order",
                "idempotency_key": "mcp-server-cancel-1",
                "expected_state_version": 1,
                "expected_attributes": {"status": "open"},
            },
            "tenant_id": "tenant-mcp-server",
            "role": "operations",
        },
    )
    assert decision["status"] == "approval_required"

    status = _call(
        server,
        "get_action_status",
        {"action_id": decision["action_id"], "tenant_id": "tenant-mcp-server"},
    )
    assert status["decision"]["action_id"] == decision["action_id"]


def test_mcp_server_lists_and_resolves_conflicts() -> None:
    server = build_server()
    adapter = server.adapter  # type: ignore[attr-defined]
    headers = {"X-Reality-Tenant": "tenant-conflict"}

    for connector, status in (("carrier-api", "delayed"), ("erp", "shipped")):
        adapter._client.post(
            "/v1/observations",
            json={
                "observation_id": f"obs_{connector}",
                "connector": connector,
                "object_type": "shipment",
                "object_id": "shp-mcp-1",
                "observed_at": datetime.now(UTC).isoformat(),
                "payload": {"id": "shp-mcp-1", "status": status},
            },
            headers=headers,
        )

    conflicts = _call(server, "list_conflicts", {"tenant_id": "tenant-conflict"})
    assert len(conflicts) == 1
    conflict_id = conflicts[0]["conflict_id"]

    fetched = _call(
        server, "get_conflict", {"conflict_id": conflict_id, "tenant_id": "tenant-conflict"}
    )
    assert fetched["attribute"] == "status"

    resolved = _call(
        server,
        "resolve_conflict",
        {
            "conflict_id": conflict_id,
            "tenant_id": "tenant-conflict",
            "resolved_value": "shipped",
            "reason": "carrier lagged",
        },
    )
    assert resolved["status"] == "resolved"
    assert _call(server, "list_conflicts", {"tenant_id": "tenant-conflict", "status": "open"}) == []


@pytest.fixture
def live_reality_server() -> Iterator[str]:
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_mcp_server_can_talk_to_a_real_network_deployment(live_reality_server: str) -> None:
    server = build_server(base_url=live_reality_server)
    adapter = server.adapter  # type: ignore[attr-defined]
    assert isinstance(adapter._client, httpx.Client)

    adapter._client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_mcp_network_1",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "order-network-1",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "order-network-1", "status": "open"},
        },
        headers={"X-Reality-Tenant": "tenant-mcp-network"},
    )

    state = _call(server, "get_world_state", {"tenant_id": "tenant-mcp-network"})
    assert state[0]["entity_id"] == "order:order-network-1"
