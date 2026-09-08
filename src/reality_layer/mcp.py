from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reality_layer.actions.models import ActionProposal
from reality_layer.api.app import create_app


class RealityMcpAdapter:
    """MCP-tool-shaped facade over the canonical REST application contract."""

    def __init__(self, app: FastAPI | None = None) -> None:
        self._client = TestClient(app or create_app())

    def _headers(self, tenant_id: str, role: str = "observer") -> dict[str, str]:
        return {
            "X-Reality-Tenant": tenant_id,
            "X-Reality-Role": role,
        }

    @staticmethod
    def _result(response: Any) -> Any:
        response.raise_for_status()
        return response.json()

    def get_world_state(
        self, tenant_id: str, entity_type: str | None = None
    ) -> list[dict[str, Any]]:
        response = self._client.get(
            "/v1/world-state",
            params={"entity_type": entity_type} if entity_type else None,
            headers=self._headers(tenant_id),
        )
        return cast(list[dict[str, Any]], self._result(response))

    def query_entities(
        self, tenant_id: str, entity_type: str | None = None
    ) -> list[dict[str, Any]]:
        response = self._client.get(
            "/v1/entities",
            params={"entity_type": entity_type} if entity_type else None,
            headers=self._headers(tenant_id),
        )
        return cast(list[dict[str, Any]], self._result(response))

    def propose_action(
        self, proposal: ActionProposal, tenant_id: str, role: str
    ) -> dict[str, Any]:
        response = self._client.post(
            "/v1/actions",
            json=proposal.model_dump(mode="json"),
            headers=self._headers(tenant_id, role),
        )
        return cast(dict[str, Any], self._result(response))

    def get_action_status(self, action_id: str, tenant_id: str) -> dict[str, Any]:
        response = self._client.get(
            f"/v1/actions/{action_id}",
            headers=self._headers(tenant_id),
        )
        return cast(dict[str, Any], self._result(response))

    def get_proof(self, action_id: str, tenant_id: str) -> dict[str, Any]:
        response = self._client.get(
            f"/v1/actions/{action_id}/proof",
            headers=self._headers(tenant_id),
        )
        return cast(dict[str, Any], self._result(response))

    def diff_since(
        self, tenant_id: str, since_commit: str | None = None
    ) -> list[dict[str, Any]]:
        response = self._client.get(
            "/v1/diffs",
            params={"since_commit": since_commit} if since_commit else None,
            headers=self._headers(tenant_id),
        )
        return cast(list[dict[str, Any]], self._result(response))
