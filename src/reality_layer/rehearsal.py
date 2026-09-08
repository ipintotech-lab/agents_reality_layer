from datetime import UTC, datetime

from reality_layer.actions.models import (
    ActionProposal,
    ActionStatus,
    ActionType,
    ApprovalRequest,
    ProofBundle,
)
from reality_layer.actions.service import ActionService
from reality_layer.config import Settings
from reality_layer.connectors.shopify import ShopifyConnector
from reality_layer.worker.verifier import VerifierWorker
from reality_layer.world_state.models import Observation
from reality_layer.world_state.service import WorldStateService


def run_local_rehearsal(
    tenant_id: str = "demo",
    order_id: str = "rehearsal-order",
) -> ProofBundle:
    """Run the complete MVP loop against the deterministic local Shopify adapter."""
    world_state = WorldStateService()
    actions = ActionService()
    shopify = ShopifyConnector()

    state = world_state.ingest(
        tenant_id,
        Observation(
            observation_id="obs_rehearsal_seed",
            connector="shopify",
            object_type="order",
            object_id=order_id,
            observed_at=datetime.now(UTC),
            payload={"id": order_id, "status": "open"},
        ),
    )
    proposal = ActionProposal(
        action_type=ActionType.cancel_order,
        target_entity=f"order:{order_id}",
        reason="Deterministic local rehearsal of the MVP control loop.",
        evidence_refs=["obs_rehearsal_seed"],
        idempotency_key=f"rehearsal-cancel:{tenant_id}:{order_id}",
        expected_state_version=state.state_version,
        expected_attributes={"status": "open"},
    )
    decision = actions.propose(proposal, "operations", tenant_id)
    if decision.status is not ActionStatus.approval_required:
        raise RuntimeError(f"Rehearsal proposal was not approval-required: {decision.status}")

    approved = actions.approve(
        decision.action_id,
        ApprovalRequest(reason="Approved by the local rehearsal operator."),
        "operations",
        tenant_id,
        state,
    )
    if approved.status is not ActionStatus.approved:
        raise RuntimeError(f"Rehearsal approval failed: {approved.status}")

    receipt = actions.execute(
        decision.action_id,
        tenant_id,
        shopify.cancel_order,
        state,
    )
    if receipt.status is not ActionStatus.provider_accepted:
        raise RuntimeError(f"Rehearsal execution failed: {receipt.status}")

    worker = VerifierWorker(
        action_service=actions,
        world_state_service=world_state,
        read_order=shopify.read_order,
        normalizer=shopify,
        settings=Settings(
            verifier_initial_interval_seconds=0.0,
            verifier_backoff_factor=1.0,
            verifier_max_interval_seconds=0.0,
            verifier_max_attempts=1,
            verifier_timeout_seconds=1.0,
        ),
        sleep=lambda _: None,
    )
    verified = worker.verify_action(tenant_id, decision.action_id)
    if verified.status is not ActionStatus.verified:
        raise RuntimeError(f"Rehearsal verification failed: {verified.status}")

    final_state = world_state.get_order(tenant_id, order_id)
    commit = world_state.get_commit_for_state(tenant_id, final_state)
    return actions.proof(decision.action_id, tenant_id, commit=commit)


def run_local_rehearsals(
    tenant_id: str = "demo",
    order_id: str = "rehearsal-order",
    runs: int = 1,
) -> list[ProofBundle]:
    """Run isolated rehearsals repeatedly to verify reset-safe demo behavior."""
    if runs < 1:
        raise ValueError("Rehearsal runs must be at least 1.")
    return [
        run_local_rehearsal(
            tenant_id,
            order_id if runs == 1 else f"{order_id}-{index}",
        )
        for index in range(1, runs + 1)
    ]
