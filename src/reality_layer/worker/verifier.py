"""Read-after-write verification worker.

The verifier closes the trustworthy loop: a provider ``2xx`` only moves an action to
``provider_accepted``. This worker independently re-reads the order from the source system,
ingests the response as a fresh immutable observation, compiles it into World State, and
compares the effective state with the action's expected outcome. It retries with bounded
exponential backoff until the state is confirmed (``verified``), contradicts the expectation
(``state_diverged``), or the attempt/time budget is exhausted (``verification_failed``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from reality_layer.actions.models import ActionDecision
from reality_layer.actions.persistence import ActionEventPersistenceService
from reality_layer.actions.service import ActionService
from reality_layer.config import Settings, get_settings
from reality_layer.connectors.shopify import ShopifyConnector
from reality_layer.storage import LocalObjectStore, ObjectStore
from reality_layer.world_state.models import Observation
from reality_layer.world_state.persistence import CompilerPersistenceService
from reality_layer.world_state.service import WorldStateService


class _SessionFactory(Protocol):
    def __call__(self) -> Any: ...


class _Normalizer(Protocol):
    name: str

    def normalize(self, payload: dict[str, Any]) -> Observation: ...


ReadOrder = Callable[[str], dict[str, Any]]


class VerifierWorker:
    def __init__(
        self,
        *,
        action_service: ActionService,
        world_state_service: WorldStateService,
        read_order: ReadOrder,
        settings: Settings | None = None,
        normalizer: _Normalizer | None = None,
        object_store: ObjectStore | None = None,
        session_factory: _SessionFactory | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings or get_settings()
        self._actions = action_service
        self._world_state = world_state_service
        self._read_order = read_order
        self._normalizer: _Normalizer = normalizer or ShopifyConnector()
        self._session_factory = session_factory
        self._object_store = object_store or (
            LocalObjectStore(Path(self._settings.object_storage_root))
            if session_factory is not None
            else None
        )
        self._sleep = sleep
        self._monotonic = monotonic

    # -- sweeping -----------------------------------------------------------------

    def pending_actions(self) -> list[tuple[str, str]]:
        """Discover ``(tenant_id, action_id)`` pairs that still need verification."""
        if self._session_factory is None:
            return self._actions.pending_verifications()

        session = self._session_factory()
        try:
            persistence = ActionEventPersistenceService(session)
            for tenant_id in persistence.repository.distinct_tenants():
                for event in persistence.list_for_tenant(tenant_id):
                    self._actions.restore(event)
        finally:
            session.close()
        return self._actions.pending_verifications()

    def run_once(self) -> list[ActionDecision]:
        """Run one verification sweep over every pending action."""
        results: list[ActionDecision] = []
        for tenant_id, action_id in self.pending_actions():
            results.append(self.verify_action(tenant_id, action_id))
        return results

    def run_forever(self) -> None:  # pragma: no cover - long-running entrypoint
        while True:
            self.run_once()
            self._sleep(self._settings.verifier_sweep_interval_seconds)

    # -- per-action polling ------------------------------------------------------

    def verify_action(self, tenant_id: str, action_id: str) -> ActionDecision:
        proposal = self._actions.get_proposal(action_id, tenant_id)
        order_id = proposal.target_entity.removeprefix("order:")

        max_attempts = max(1, self._settings.verifier_max_attempts)
        interval = self._settings.verifier_initial_interval_seconds
        deadline = self._monotonic() + self._settings.verifier_timeout_seconds
        decision: ActionDecision | None = None

        for attempt in range(1, max_attempts + 1):
            state = self._ingest_verification_read(tenant_id, order_id)
            out_of_time = self._monotonic() >= deadline
            is_final = attempt >= max_attempts or out_of_time
            decision = self._actions.verify(
                action_id, tenant_id, state, is_final_attempt=is_final
            )
            self._persist_events(tenant_id, action_id)
            if decision.status in ActionService.TERMINAL_VERIFICATION_STATUSES:
                return decision
            if is_final:
                break
            interval = min(interval, max(0.0, deadline - self._monotonic()))
            self._sleep(interval)
            interval = min(
                interval * self._settings.verifier_backoff_factor,
                self._settings.verifier_max_interval_seconds,
            )

        if decision is None:  # pragma: no cover - defensive; loop always runs once
            raise RuntimeError("Verification loop produced no decision")
        return decision

    # -- observation ingestion -------------------------------------------------------

    def _ingest_verification_read(self, tenant_id: str, order_id: str) -> Any:
        payload = self._read_order(order_id)
        observation = self._normalizer.normalize(payload)
        # Every poll is a distinct immutable observation, so it must not collide with the
        # deterministic connector observation id (which would be deduplicated on ingest).
        observation = observation.model_copy(
            update={"observation_id": f"{observation.observation_id}_verify_{uuid4().hex[:12]}"}
        )

        if self._session_factory is None:
            return self._world_state.ingest(
                tenant_id, observation, cause="verification", assurance_level="verified"
            )

        session = self._session_factory()
        try:
            state = self._compile_with_persistence(session, tenant_id, observation, payload)
            session.commit()
            return state
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _compile_with_persistence(
        self,
        session: Any,
        tenant_id: str,
        observation: Observation,
        payload: dict[str, Any],
    ) -> Any:
        from reality_layer.connectors.observe import ObservedPayload
        from reality_layer.connectors.persistence import ObservationIngestionService

        compiler = CompilerPersistenceService(session)
        entity_id = f"{observation.object_type}:{observation.object_id}"
        existing = compiler.load_state(tenant_id, entity_id)
        if existing is not None:
            previous_commit = (
                compiler.load_commit(tenant_id, existing.commit_id)
                if existing.commit_id
                else None
            )
            self._world_state.hydrate(
                existing,
                existing.commit_id,
                previous_commit.hash if previous_commit else None,
            )

        if self._object_store is not None:
            import json

            stored = self._object_store.put_raw_payload(
                tenant_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                "application/json",
            )
            ObservationIngestionService(session).persist(
                tenant_id, ObservedPayload(observation, stored)
            )

        state = self._world_state.ingest(
            tenant_id, observation, cause="verification", assurance_level="verified"
        )
        if existing is None or state.commit_id != existing.commit_id:
            compiler.persist(
                state, self._world_state.get_commit_for_state(tenant_id, state)
            )
        return state

    def _persist_events(self, tenant_id: str, action_id: str) -> None:
        if self._session_factory is None:
            return
        session = self._session_factory()
        try:
            persistence = ActionEventPersistenceService(session)
            for event in self._actions.events(action_id, tenant_id):
                persistence.persist(event)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
