import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

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
from reality_layer.reality_git import validate_commit_chain, validate_event_chain
from reality_layer.worker.verifier import VerifierWorker
from reality_layer.world_state.models import Observation
from reality_layer.world_state.service import WorldStateService

_T = TypeVar("_T")


class RehearsalFault(StrEnum):
    """Fault to inject into a rehearsal run to prove the loop fails safe."""

    none = "none"
    provider_error = "provider_error"
    verification_divergence = "verification_divergence"


# The protective terminal status each scenario is expected to reach. A run is only
# "protected" when it lands exactly here: the loop never claims a write it cannot
# independently confirm.
_EXPECTED_TERMINAL: dict[RehearsalFault, str] = {
    RehearsalFault.none: ActionStatus.verified.value,
    RehearsalFault.provider_error: ActionStatus.approved.value,
    RehearsalFault.verification_divergence: ActionStatus.state_diverged.value,
}


@dataclass(frozen=True)
class RehearsalResult:
    """Outcome of a single rehearsal run, including per-step latency."""

    fault: RehearsalFault
    terminal_status: str
    protected: bool
    step_latencies_ms: dict[str, float]
    proof: ProofBundle | None

    @property
    def verified(self) -> bool:
        return self.terminal_status == ActionStatus.verified.value


def rehearsal_summary(proofs: list[ProofBundle], elapsed_seconds: float) -> dict[str, Any]:
    """Return a stable operator-facing summary for a rehearsal batch."""
    verified_runs = sum(proof.status is ActionStatus.verified for proof in proofs)
    return {
        "total_runs": len(proofs),
        "verified_runs": verified_runs,
        "failed_runs": len(proofs) - verified_runs,
        "all_verified": bool(proofs) and verified_runs == len(proofs),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
        "action_ids": [proof.action_id for proof in proofs],
        "verification_commit_ids": [proof.verification_commit_id for proof in proofs],
    }


def rehearsal_scenario_summary(
    results: list[RehearsalResult], elapsed_seconds: float
) -> dict[str, Any]:
    """Summarize a batch of (possibly fault-injected) rehearsal runs with latency."""
    protected_runs = sum(result.protected for result in results)
    steps = sorted({step for result in results for step in result.step_latencies_ms})
    slowest_step_ms = {
        step: round(
            max(
                (
                    result.step_latencies_ms[step]
                    for result in results
                    if step in result.step_latencies_ms
                ),
                default=0.0,
            ),
            3,
        )
        for step in steps
    }
    return {
        "total_runs": len(results),
        "protected_runs": protected_runs,
        "unprotected_runs": len(results) - protected_runs,
        "all_protected": bool(results) and protected_runs == len(results),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
        "faults": [result.fault.value for result in results],
        "terminal_statuses": [result.terminal_status for result in results],
        "slowest_step_ms": slowest_step_ms,
        "slowest_run_ms": round(
            max((sum(result.step_latencies_ms.values()) for result in results), default=0.0),
            3,
        ),
    }


def run_rehearsal(
    tenant_id: str = "demo",
    order_id: str = "rehearsal-order",
    *,
    fault: RehearsalFault = RehearsalFault.none,
) -> RehearsalResult:
    """Run the complete MVP loop against the deterministic local Shopify adapter.

    With ``fault`` set, an operational failure is injected and the run is judged by
    whether the loop reaches its protective terminal status rather than ``verified``.
    """
    world_state = WorldStateService()
    actions = ActionService()
    shopify = ShopifyConnector()
    latencies: dict[str, float] = {}

    def _timed(name: str, call: Callable[[], _T]) -> _T:
        start = time.perf_counter()
        try:
            return call()
        finally:
            latencies[name] = round((time.perf_counter() - start) * 1000, 3)

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
    decision = _timed("propose", lambda: actions.propose(proposal, "operations", tenant_id))
    if decision.status is not ActionStatus.approval_required:
        raise RuntimeError(f"Rehearsal proposal was not approval-required: {decision.status}")

    approved = _timed(
        "approve",
        lambda: actions.approve(
            decision.action_id,
            ApprovalRequest(reason="Approved by the local rehearsal operator."),
            "operations",
            tenant_id,
            state,
        ),
    )
    if approved.status is not ActionStatus.approved:
        raise RuntimeError(f"Rehearsal approval failed: {approved.status}")

    if fault is RehearsalFault.provider_error:
        def _failing_executor(*_args: object, **_kwargs: object) -> Any:
            raise RuntimeError(
                "Injected provider failure: Shopify rejected the cancel_order write."
            )

        try:
            _timed(
                "execute",
                lambda: actions.execute(
                    decision.action_id, tenant_id, _failing_executor, state
                ),
            )
        except RuntimeError:
            pass
        terminal = actions.get_decision(decision.action_id, tenant_id).status.value
        return RehearsalResult(
            fault=fault,
            terminal_status=terminal,
            protected=terminal == _EXPECTED_TERMINAL[fault],
            step_latencies_ms=latencies,
            proof=None,
        )

    receipt = _timed(
        "execute",
        lambda: actions.execute(decision.action_id, tenant_id, shopify.cancel_order, state),
    )
    if receipt.status is not ActionStatus.provider_accepted:
        raise RuntimeError(f"Rehearsal execution failed: {receipt.status}")

    def _diverged_read(order: str) -> dict[str, Any]:
        # The provider "accepted" the write but the source system still reports the
        # order open; verification must contradict the expected outcome.
        return {"id": order, "status": "open"}

    read_order = (
        _diverged_read
        if fault is RehearsalFault.verification_divergence
        else shopify.read_order
    )

    worker = VerifierWorker(
        action_service=actions,
        world_state_service=world_state,
        read_order=read_order,
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
    verified = _timed(
        "verify", lambda: worker.verify_action(tenant_id, decision.action_id)
    )

    final_state = world_state.get_order(tenant_id, order_id)
    commit = world_state.get_commit_for_state(tenant_id, final_state)
    proof = _timed(
        "proof", lambda: actions.proof(decision.action_id, tenant_id, commit=commit)
    )
    validate_commit_chain(world_state.list_commits(tenant_id))
    validate_event_chain(proof.events)

    terminal = verified.status.value
    protected = terminal == _EXPECTED_TERMINAL[fault]
    if fault is RehearsalFault.none and not protected:
        raise RuntimeError(f"Rehearsal verification failed: {terminal}")
    return RehearsalResult(
        fault=fault,
        terminal_status=terminal,
        protected=protected,
        step_latencies_ms=latencies,
        proof=proof,
    )


def run_local_rehearsal(
    tenant_id: str = "demo",
    order_id: str = "rehearsal-order",
) -> ProofBundle:
    """Run the complete MVP happy-path loop and return its proof bundle."""
    result = run_rehearsal(tenant_id, order_id)
    if result.proof is None:  # pragma: no cover - happy path always yields a proof
        raise RuntimeError("Rehearsal did not produce a proof bundle.")
    return result.proof


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


def run_rehearsals(
    tenant_id: str = "demo",
    order_id: str = "rehearsal-order",
    runs: int = 1,
    *,
    fault: RehearsalFault = RehearsalFault.none,
) -> list[RehearsalResult]:
    """Run isolated rehearsal scenarios repeatedly, injecting ``fault`` into each."""
    if runs < 1:
        raise ValueError("Rehearsal runs must be at least 1.")
    return [
        run_rehearsal(
            tenant_id,
            order_id if runs == 1 else f"{order_id}-{index}",
            fault=fault,
        )
        for index in range(1, runs + 1)
    ]
