from typing import Any, cast

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reality_layer.actions.models import ActionProposal
from reality_layer.api.app import create_app


class RealityMcpAdapter:
    """MCP-tool-shaped facade over the canonical REST application contract.

    Defaults to an in-process ASGI transport (``TestClient``) for local
    scripted use. Pass ``base_url`` to talk to a real, network-addressable
    Reality Layer deployment instead (e.g. one started with ``reality serve``).
    """

    def __init__(self, app: FastAPI | None = None, base_url: str | None = None) -> None:
        self._client: httpx.Client
        if base_url is not None:
            self._client = httpx.Client(base_url=base_url)
        else:
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
        self,
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            key: value
            for key, value in {
                "entity_type": entity_type,
                "state": state,
                "freshness": freshness,
                "min_confidence": min_confidence,
            }.items()
            if value is not None
        }
        response = self._client.get(
            "/v1/world-state",
            params=params or None,
            headers=self._headers(tenant_id),
        )
        return cast(list[dict[str, Any]], self._result(response))

    def query_entities(
        self,
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            key: value
            for key, value in {
                "entity_type": entity_type,
                "state": state,
                "freshness": freshness,
                "min_confidence": min_confidence,
            }.items()
            if value is not None
        }
        response = self._client.get(
            "/v1/entities",
            params=params or None,
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

    def list_conflicts(
        self, tenant_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        response = self._client.get(
            "/v1/conflicts",
            params={"status": status} if status else None,
            headers=self._headers(tenant_id),
        )
        return cast(list[dict[str, Any]], self._result(response))

    def get_conflict(self, conflict_id: str, tenant_id: str) -> dict[str, Any]:
        response = self._client.get(
            f"/v1/conflicts/{conflict_id}",
            headers=self._headers(tenant_id),
        )
        return cast(dict[str, Any], self._result(response))

    def resolve_conflict(
        self,
        conflict_id: str,
        tenant_id: str,
        resolved_value: Any,
        reason: str,
        role: str = "operations",
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/v1/conflicts/{conflict_id}/resolve",
            json={"resolved_value": resolved_value, "reason": reason},
            headers=self._headers(tenant_id, role),
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
