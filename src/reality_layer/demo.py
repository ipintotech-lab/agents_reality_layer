"""Scripted agent demo driven entirely through the public contracts.

The agent side uses the MCP tool facade (:class:`RealityMcpAdapter`); the operator
and system side use the canonical REST API. Both share a single application
instance so the scripted loop exercises real cross-actor state.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reality_layer.actions.models import ActionProposal, ActionType
from reality_layer.api.app import create_app
from reality_layer.connectors.easypost import EasyPostConnector
from reality_layer.mcp import RealityMcpAdapter
from reality_layer.world_state.models import Observation


@dataclass
class DemoStep:
    """One scripted interaction, attributed to an actor and a channel."""

    name: str
    actor: str  # agent | operator | system
    channel: str  # mcp | rest
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DemoRun:
    tenant_id: str
    order_id: str
    steps: list[DemoStep]
    denied: dict[str, Any]
    proposal_only: dict[str, Any]
    proof: dict[str, Any]

    @property
    def verified(self) -> bool:
        return self.proof.get("assurance_level") == "verified"


def _headers(tenant_id: str, role: str = "system") -> dict[str, str]:
    return {"X-Reality-Tenant": tenant_id, "X-Reality-Role": role}


def _attribute(entity: dict[str, Any] | None, name: str) -> Any:
    if not entity:
        return None
    attribute = entity.get("attributes", {}).get(name)
    return attribute["value"] if attribute else None


def _confidence(entity: dict[str, Any] | None, name: str) -> float | None:
    if not entity:
        return None
    attribute = entity.get("attributes", {}).get(name)
    return attribute["confidence"] if attribute else None


def _cancel_proposal(
    order_id: str, key: str, order_view: dict[str, Any] | None
) -> ActionProposal:
    return ActionProposal(
        action_type=ActionType.cancel_order,
        target_entity=f"order:{order_id}",
        reason="Customer opened a duplicate order; cancel the unfulfilled copy.",
        evidence_refs=[f"obs_shopify_seed_{order_id}"],
        idempotency_key=f"demo-{key}-{order_id}",
        expected_state_version=(order_view or {}).get("state_version", 1),
        expected_attributes={"status": "open"},
    )


def _hold_proposal(order_id: str, order_view: dict[str, Any] | None) -> ActionProposal:
    return ActionProposal(
        action_type=ActionType.hold_order,
        target_entity=f"order:{order_id}",
        reason="Fraud review flagged the billing address; place a temporary hold.",
        evidence_refs=[f"obs_shopify_seed_{order_id}"],
        idempotency_key=f"demo-hold-{order_id}",
        expected_state_version=(order_view or {}).get("state_version", 1),
        expected_attributes={"status": "open"},
    )


def run_agent_demo(
    tenant_id: str = "demo",
    order_id: str = "demo-1001",
    *,
    app: FastAPI | None = None,
) -> DemoRun:
    """Run the happy path, the policy-control path, and the proposal-only path."""
    app = app or create_app()
    agent = RealityMcpAdapter(app)
    control_plane = TestClient(app)
    steps: list[DemoStep] = []
    observed_at = datetime.now(UTC).isoformat()

    # 1. Real observations are ingested from two independent sources.
    shipment_id = f"ship-{order_id}"
    # A distinct observation id from the connector's deterministic verify-time id,
    # so read-after-write ingestion is not deduplicated against the seed.
    order_obs = Observation(
        observation_id=f"obs_shopify_seed_{order_id.replace('_', '-')}",
        connector="shopify",
        object_type="order",
        object_id=order_id,
        observed_at=datetime.now(UTC),
        payload={"id": order_id, "status": "open", "currency": "USD", "total_price": "129.00"},
    )
    shipment_obs = EasyPostConnector().normalize(
        {
            "id": shipment_id,
            "tracking_code": "1Z999AA10123456784",
            "status": "in_transit",
            "observed_at": observed_at,
        }
    )
    for observation in (order_obs, shipment_obs):
        response = control_plane.post(
            "/v1/observations",
            json=json.loads(observation.model_dump_json()),
            headers=_headers(tenant_id),
        )
        response.raise_for_status()
    steps.append(
        DemoStep(
            "observe",
            "system",
            "rest",
            f"Ingested Shopify order {order_id} and EasyPost shipment {shipment_id}.",
            {"observations": [order_obs.observation_id, shipment_obs.observation_id]},
        )
    )

    # 2. The agent reads permission-filtered World State with provenance.
    world = agent.get_world_state(tenant_id)
    order_view = next(
        (e for e in world if e["entity_id"] in {order_id, f"order:{order_id}"}), None
    )
    steps.append(
        DemoStep(
            "agent_query",
            "agent",
            "mcp",
            (
                f"Agent read {len(world)} entities; order {order_id} is "
                f"'{_attribute(order_view, 'status')}' at confidence "
                f"{_confidence(order_view, 'status')}."
            ),
            {"entities": [e["entity_id"] for e in world]},
        )
    )

    # 3. Policy-control path: an observer cannot propose a write.
    denied = agent.propose_action(
        _cancel_proposal(order_id, "denied", order_view), tenant_id, "observer"
    )
    steps.append(
        DemoStep(
            "policy_denied",
            "agent",
            "mcp",
            f"Observer cancel_order denied by rule '{denied.get('matched_rule')}'.",
            denied,
        )
    )

    # 4. Proposal-only path: hold_order is never executed in the MVP.
    proposal_only = agent.propose_action(
        _hold_proposal(order_id, order_view), tenant_id, "operations"
    )
    steps.append(
        DemoStep(
            "proposal_only",
            "agent",
            "mcp",
            (
                f"hold_order returned '{proposal_only['status']}' by rule "
                f"'{proposal_only.get('matched_rule')}' and is not executed."
            ),
            proposal_only,
        )
    )

    # 5. Happy path: the agent proposes cancel_order.
    decision = agent.propose_action(
        _cancel_proposal(order_id, "cancel", order_view), tenant_id, "operations"
    )
    if decision["status"] != "approval_required":
        raise RuntimeError(f"Expected approval_required, got {decision['status']}")
    action_id = decision["action_id"]
    steps.append(
        DemoStep(
            "propose",
            "agent",
            "mcp",
            f"Agent proposed cancel_order -> {decision['status']} "
            f"(needs {decision['required_role']}).",
            decision,
        )
    )

    # 6. An Operations approver reviews and approves.
    approved = control_plane.post(
        f"/v1/actions/{action_id}/approve",
        json={"reason": "Reviewed typed request, reason, and evidence; confirmed duplicate."},
        headers=_headers(tenant_id, "operations"),
    )
    approved.raise_for_status()
    steps.append(
        DemoStep(
            "approve",
            "operator",
            "rest",
            "Operations approver approved the proposal.",
            approved.json(),
        )
    )

    # 7. The gateway executes idempotently against the provider.
    receipt = control_plane.post(
        f"/v1/actions/{action_id}/execute", headers=_headers(tenant_id)
    )
    receipt.raise_for_status()
    steps.append(
        DemoStep(
            "execute",
            "system",
            "rest",
            f"Provider accepted request {receipt.json()['provider_request_id']} "
            "(not treated as proof).",
            receipt.json(),
        )
    )

    # 8. Independent read-after-write verification.
    verified = control_plane.post(
        f"/v1/actions/{action_id}/verify", headers=_headers(tenant_id)
    )
    verified.raise_for_status()
    steps.append(
        DemoStep(
            "verify",
            "system",
            "rest",
            f"Independent verification: {verified.json()['status']}.",
            verified.json(),
        )
    )

    # 9. The agent reads the derived status and the proof bundle.
    status = agent.get_action_status(action_id, tenant_id)
    proof = agent.get_proof(action_id, tenant_id)
    steps.append(
        DemoStep(
            "proof",
            "agent",
            "mcp",
            (
                f"Status '{status['decision']['status']}'; proof assurance "
                f"'{proof['assurance_level']}' over {len(proof['hash_chain'])} "
                "hash-linked events."
            ),
            {"assurance_level": proof["assurance_level"], "warnings": proof["warnings"]},
        )
    )

    # 10. The agent reads the semantic diff the action produced.
    diffs = agent.diff_since(tenant_id)
    steps.append(
        DemoStep(
            "diff",
            "agent",
            "mcp",
            f"{len(diffs)} commits; latest cause '{diffs[-1]['cause'] if diffs else '-'}'.",
            {"commits": [d["commit_id"] for d in diffs]},
        )
    )

    return DemoRun(
        tenant_id=tenant_id,
        order_id=order_id,
        steps=steps,
        denied=denied,
        proposal_only=proposal_only,
        proof=proof,
    )


def demo_transcript(run: DemoRun) -> str:
    """Render a human-readable transcript of a demo run."""
    lines = [f"Reality Layer agent demo — tenant={run.tenant_id} order={run.order_id}", ""]
    for index, step in enumerate(run.steps, start=1):
        lines.append(f"{index:>2}. [{step.actor}/{step.channel}] {step.name}")
        lines.append(f"    {step.summary}")
    lines.append("")
    lines.append(
        f"Result: assurance_level={run.proof['assurance_level']} "
        f"status={run.proof['status']} verified={run.verified}"
    )
    return "\n".join(lines)
