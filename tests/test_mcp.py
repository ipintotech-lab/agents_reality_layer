from datetime import UTC, datetime

from reality_layer.actions.models import ActionProposal
from reality_layer.mcp import RealityMcpAdapter


def _proposal() -> ActionProposal:
    return ActionProposal(
        action_type="cancel_order",
        target_entity="order:order-1",
        reason="Duplicate test order",
        idempotency_key="mcp-cancel-order-1",
        expected_state_version=1,
        expected_attributes={"status": "open"},
    )


def test_mcp_adapter_uses_rest_contract_for_state_and_action_tools() -> None:
    adapter = RealityMcpAdapter()
    adapter._client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_mcp_1",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "order-1",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "order-1", "status": "open"},
        },
        headers={"X-Reality-Tenant": "tenant-mcp"},
    )

    state = adapter.get_world_state("tenant-mcp")
    decision = adapter.propose_action(_proposal(), "tenant-mcp", "operations")
    status = adapter.get_action_status(decision["action_id"], "tenant-mcp")

    assert state[0]["entity_id"] == "order:order-1"
    assert decision["status"] == "approval_required"
    assert status["decision"]["action_id"] == decision["action_id"]


def test_mcp_adapter_keeps_tenant_boundaries() -> None:
    adapter = RealityMcpAdapter()
    adapter._client.post(
        "/v1/observations",
        json={
            "observation_id": "obs_mcp_2",
            "connector": "shopify",
            "object_type": "order",
            "object_id": "order-2",
            "observed_at": datetime.now(UTC).isoformat(),
            "payload": {"id": "order-2", "status": "open"},
        },
        headers={"X-Reality-Tenant": "tenant-a"},
    )

    assert adapter.get_world_state("tenant-b") == []


def test_mcp_adapter_lists_gets_and_resolves_conflicts() -> None:
    adapter = RealityMcpAdapter()
    for connector, status in (("carrier-api", "delayed"), ("erp", "shipped")):
        adapter._client.post(
            "/v1/observations",
            json={
                "observation_id": f"obs_conflict_{connector}",
                "connector": connector,
                "object_type": "shipment",
                "object_id": "shp-1",
                "observed_at": datetime.now(UTC).isoformat(),
                "payload": {"id": "shp-1", "status": status},
            },
            headers={"X-Reality-Tenant": "tenant-c"},
        )

    conflicts = adapter.list_conflicts("tenant-c")
    assert len(conflicts) == 1
    conflict_id = conflicts[0]["conflict_id"]
    assert adapter.get_conflict(conflict_id, "tenant-c")["attribute"] == "status"

    resolved = adapter.resolve_conflict(conflict_id, "tenant-c", "shipped", "carrier lagged")
    assert resolved["status"] == "resolved"
    assert adapter.list_conflicts("tenant-c", "open") == []
