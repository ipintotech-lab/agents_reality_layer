from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from reality_layer.actions.models import (
    ActionProposal,
    ActionStatus,
    ApprovalRequest,
    ExecutionReceipt,
)
from reality_layer.actions.service import ActionService
from reality_layer.config import Settings
from reality_layer.worker.verifier import VerifierWorker
from reality_layer.world_state.models import Observation
from reality_layer.world_state.service import WorldStateService

TENANT = "demo"
ORDER = "o1"
ACTION = "order:o1"


def _settings(**overrides: object) -> Settings:
    base = dict(
        verifier_initial_interval_seconds=0.0,
        verifier_backoff_factor=2.0,
        verifier_max_interval_seconds=1.0,
        verifier_max_attempts=4,
        verifier_timeout_seconds=1000.0,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _observe(ws: WorldStateService, status: str) -> None:
    ws.ingest(
        TENANT,
        Observation(
            observation_id="obs_shopify_seed",
            connector="shopify",
            object_type="order",
            object_id=ORDER,
            observed_at=datetime.now(UTC),
            payload={"id": ORDER, "status": status},
        ),
    )


def _approved_and_executed_action(svc: ActionService, ws: WorldStateService) -> str:
    proposal = ActionProposal(
        action_type="cancel_order",
        target_entity=ACTION,
        reason="Duplicate test order",
        idempotency_key="demo-cancel-order-o1",
        expected_state_version=1,
        expected_attributes={"status": "open"},
    )
    decision = svc.propose(proposal, "operations", TENANT)
    svc.approve(
        decision.action_id,
        ApprovalRequest(reason="approved"),
        "operations",
        TENANT,
        ws.get_order(TENANT, ORDER),
    )
    svc.execute(
        decision.action_id,
        TENANT,
        lambda action_id, order_id, key: ExecutionReceipt(
            action_id=action_id,
            status=ActionStatus.provider_accepted,
            provider="shopify",
            provider_request_id="shopify-test-1",
            idempotency_key=key,
        ),
    )
    return decision.action_id


def _reader(statuses: list[str]) -> object:
    values: Iterator[str] = iter(statuses)
    last = statuses[-1]

    def read_order(order_id: str) -> dict[str, object]:
        return {"id": order_id, "status": next(values, last)}

    return read_order


def _worker(
    svc: ActionService, ws: WorldStateService, statuses: list[str], **settings: object
) -> VerifierWorker:
    sleeps: list[float] = []
    worker = VerifierWorker(
        action_service=svc,
        world_state_service=ws,
        read_order=_reader(statuses),  # type: ignore[arg-type]
        settings=_settings(**settings),
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
    )
    worker.recorded_sleeps = sleeps  # type: ignore[attr-defined]
    return worker


def test_verifies_on_first_poll_when_state_already_cancelled() -> None:
    ws = WorldStateService()
    svc = ActionService()
    _observe(ws, "open")
    action_id = _approved_and_executed_action(svc, ws)

    decision = _worker(svc, ws, ["cancelled"]).verify_action(TENANT, action_id)

    assert decision.status is ActionStatus.verified
    events = [e.event_type for e in svc.events(action_id, TENANT)]
    assert events[-1] == "verified"
    assert "verification_pending" not in events


def test_polls_until_state_becomes_cancelled() -> None:
    ws = WorldStateService()
    svc = ActionService()
    _observe(ws, "open")
    action_id = _approved_and_executed_action(svc, ws)

    worker = _worker(svc, ws, ["open", "open", "cancelled"])
    decision = worker.verify_action(TENANT, action_id)

    assert decision.status is ActionStatus.verified
    events = [e.event_type for e in svc.events(action_id, TENANT)]
    assert events.count("verification_pending") == 2
    assert events[-1] == "verified"
    # Backoff is non-decreasing between the two pending attempts.
    sleeps = worker.recorded_sleeps
    assert sleeps[0] <= sleeps[1]


def test_diverged_state_after_exhausting_attempts() -> None:
    ws = WorldStateService()
    svc = ActionService()
    _observe(ws, "open")
    action_id = _approved_and_executed_action(svc, ws)

    decision = _worker(svc, ws, ["open"], verifier_max_attempts=3).verify_action(TENANT, action_id)

    assert decision.status is ActionStatus.state_diverged
    events = [e.event_type for e in svc.events(action_id, TENANT)]
    assert events.count("verification_pending") == 2
    assert events[-1] == "state_diverged"


def test_timeout_marks_verification_failed_when_no_status_read() -> None:
    svc = ActionService()
    ws = WorldStateService()
    _observe(ws, "open")
    action_id = _approved_and_executed_action(svc, ws)

    decision = svc.verify(action_id, TENANT, None, is_final_attempt=True)

    assert decision.status is ActionStatus.verification_failed


def test_pending_actions_sweep_is_driven_by_action_status() -> None:
    ws = WorldStateService()
    svc = ActionService()
    _observe(ws, "open")
    action_id = _approved_and_executed_action(svc, ws)

    worker = _worker(svc, ws, ["cancelled"])
    assert worker.pending_actions() == [(TENANT, action_id)]

    results = worker.run_once()

    assert [d.status for d in results] == [ActionStatus.verified]
    assert worker.pending_actions() == []


def test_verify_rejects_actions_that_were_not_provider_accepted() -> None:
    svc = ActionService()
    ws = WorldStateService()
    _observe(ws, "open")
    proposal = ActionProposal(
        action_type="cancel_order",
        target_entity=ACTION,
        reason="Duplicate test order",
        idempotency_key="demo-cancel-order-o1",
        expected_state_version=1,
        expected_attributes={"status": "open"},
    )
    decision = svc.propose(proposal, "operations", TENANT)

    with pytest.raises(ValueError):
        svc.verify(decision.action_id, TENANT, ws.get_order(TENANT, ORDER))
