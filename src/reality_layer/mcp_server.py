"""A network-addressable MCP server exposing the Reality Layer adapter tools.

Unlike :class:`reality_layer.mcp.RealityMcpAdapter` used in-process by the
scripted demo, this module runs a real Model Context Protocol server that any
MCP client can connect to — over stdio (spawned as a subprocess) or over the
network (``sse`` / ``streamable-http``). Point it at a running deployment with
``base_url``; without one it falls back to an in-process app, matching the
adapter's own default.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reality_layer.actions.models import ActionProposal
from reality_layer.mcp import RealityMcpAdapter

SERVER_NAME = "reality-layer"


def build_server(
    base_url: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8100,
) -> FastMCP:
    adapter = RealityMcpAdapter(base_url=base_url)
    mcp = FastMCP(SERVER_NAME, host=host, port=port)
    mcp.adapter = adapter  # type: ignore[attr-defined]  # exposed for tests/introspection

    @mcp.tool()
    def get_world_state(
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return the current World State projection for a tenant."""
        return adapter.get_world_state(tenant_id, entity_type, state, freshness, min_confidence)

    @mcp.tool()
    def query_entities(
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        """Query World State entities for a tenant with optional filters."""
        return adapter.query_entities(tenant_id, entity_type, state, freshness, min_confidence)

    @mcp.tool()
    def propose_action(proposal: dict[str, Any], tenant_id: str, role: str) -> dict[str, Any]:
        """Submit a typed action proposal for policy evaluation and, if approved, execution."""
        return adapter.propose_action(ActionProposal.model_validate(proposal), tenant_id, role)

    @mcp.tool()
    def get_action_status(action_id: str, tenant_id: str) -> dict[str, Any]:
        """Fetch the current decision/execution status of a proposed action."""
        return adapter.get_action_status(action_id, tenant_id)

    @mcp.tool()
    def get_proof(action_id: str, tenant_id: str) -> dict[str, Any]:
        """Fetch the proof bundle linking proposal, policy, execution, and verification."""
        return adapter.get_proof(action_id, tenant_id)

    @mcp.tool()
    def diff_since(tenant_id: str, since_commit: str | None = None) -> list[dict[str, Any]]:
        """Return World State commits/diffs for a tenant since a given commit."""
        return adapter.diff_since(tenant_id, since_commit)

    return mcp
