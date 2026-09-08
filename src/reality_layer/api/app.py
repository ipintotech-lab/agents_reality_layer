from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from reality_layer import __version__
from reality_layer.actions import ActionService
from reality_layer.actions.models import (
    ActionDecision,
    ActionEventRecord,
    ActionProposal,
    ActionStatusResponse,
    ApprovalRequest,
    ExecutionReceipt,
    ProofBundle,
)
from reality_layer.actions.persistence import ActionEventPersistenceService
from reality_layer.config import Settings, get_settings
from reality_layer.connectors import ShopifyConnector
from reality_layer.connectors.observe import ObservedPayload
from reality_layer.connectors.persistence import ObservationIngestionService
from reality_layer.storage import LocalObjectStore
from reality_layer.workspaces import WorkspaceService
from reality_layer.world_state import (
    CommitRecord,
    CompilerPersistenceService,
    Observation,
    OrderState,
    WorldStateService,
)


def create_app(
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> FastAPI:
    app = FastAPI(title="Reality Layer", version=__version__)
    app_settings = settings or get_settings()
    if session_factory is not None:
        make_session = session_factory
    else:
        def make_session() -> Session:
            from reality_layer.db.session import SessionLocal

            return SessionLocal()
    action_service = ActionService()
    shopify_connector = ShopifyConnector()
    world_state_service = WorldStateService()
    object_store = LocalObjectStore(Path(app_settings.object_storage_root))

    def restore_actions(tenant_id: str, session: Session) -> None:
        persistence = ActionEventPersistenceService(session)
        for event in persistence.list_for_tenant(tenant_id):
            action_service.restore(event)

    def persist_action_events(tenant_id: str, action_id: str, session: Session) -> None:
        persistence = ActionEventPersistenceService(session)
        for event in action_service.events(action_id, tenant_id):
            persistence.persist(event)

    def resolve_order_state(tenant_id: str, order_id: str) -> OrderState | None:
        if app_settings.persistence_enabled:
            session = make_session()
            try:
                state = CompilerPersistenceService(session).load_state(
                    tenant_id, f"order:{order_id}"
                )
            finally:
                session.close()
            if state is not None:
                world_state_service.hydrate(state)
                return state
        try:
            return world_state_service.get_order(tenant_id, order_id)
        except KeyError:
            return None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/observations", response_model=OrderState, status_code=201)
    def ingest_observation(
        observation: Observation,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        if not app_settings.persistence_enabled:
            return world_state_service.ingest(x_reality_tenant, observation)

        session = make_session()
        try:
            stored = object_store.put_raw_payload(
                x_reality_tenant,
                observation.model_dump_json().encode(),
                "application/json",
            )
            observed = ObservedPayload(observation, stored)
            persisted = ObservationIngestionService(session).persist(
                x_reality_tenant, observed
            )
            compiler = CompilerPersistenceService(session)
            existing = compiler.load_state(
                x_reality_tenant,
                f"{observation.object_type}:{observation.object_id}",
            )
            if existing is not None:
                previous_commit = (
                    compiler.load_commit(x_reality_tenant, existing.commit_id)
                    if existing.commit_id
                    else None
                )
                world_state_service.hydrate(
                    existing,
                    existing.commit_id,
                    previous_commit.hash if previous_commit else None,
                )
            if not persisted.created and existing is not None:
                session.commit()
                return existing
            state = world_state_service.ingest(x_reality_tenant, observation)
            if persisted.created:
                compiler.persist(
                    state,
                    world_state_service.get_commit_for_state(x_reality_tenant, state),
                )
            session.commit()
            return state
        except (OSError, SQLAlchemyError, ValueError):
            session.rollback()
            raise
        finally:
            session.close()

    @app.get("/v1/orders/{order_id}", response_model=OrderState)
    def get_order(
        order_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    state = CompilerPersistenceService(session).load_state(
                        x_reality_tenant, f"order:{order_id}"
                    )
                finally:
                    session.close()
                if state is not None:
                    return state
            return world_state_service.get_order(x_reality_tenant, order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/shipments/{shipment_id}", response_model=OrderState)
    def get_shipment(
        shipment_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    state = CompilerPersistenceService(session).load_state(
                        x_reality_tenant, f"shipment:{shipment_id}"
                    )
                finally:
                    session.close()
                if state is not None:
                    return state
            return world_state_service.get_entity(x_reality_tenant, "shipment", shipment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def resolve_commit(tenant_id: str, commit_id: str) -> CommitRecord:
        if app_settings.persistence_enabled:
            session = make_session()
            try:
                commit = CompilerPersistenceService(session).load_commit(
                    tenant_id, commit_id
                )
            finally:
                session.close()
            if commit is not None:
                return commit
        return world_state_service.get_commit(tenant_id, commit_id)

    @app.get("/v1/commits/{commit_id}", response_model=CommitRecord)
    def get_commit(
        commit_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> CommitRecord:
        try:
            return resolve_commit(x_reality_tenant, commit_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/diffs", response_model=list[CommitRecord])
    def list_diffs(
        since_commit: str | None = None,
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[CommitRecord]:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    return CompilerPersistenceService(session).list_commits(
                        x_reality_tenant, since_commit
                    )
                finally:
                    session.close()
            return world_state_service.list_commits(x_reality_tenant, since_commit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def order_value_for(tenant_id: str, target_entity: str) -> float | None:
        order_id = target_entity.removeprefix("order:")
        try:
            state = world_state_service.get_order(tenant_id, order_id)
        except KeyError:
            return None
        attribute = state.attributes.get("total_price")
        if attribute is None:
            return None
        try:
            return float(attribute.value)
        except (TypeError, ValueError):
            return None

    @app.post("/v1/actions", response_model=ActionDecision, status_code=201)
    def propose_action(
        proposal: ActionProposal,
        x_reality_role: str = Header(default="observer"),
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        workspace_mode = app_settings.workspace_mode
        value_limit = app_settings.write_value_limit
        if app_settings.persistence_enabled:
            session = make_session()
            try:
                workspace_policy = WorkspaceService(session).policy(x_reality_tenant)
                workspace_mode = workspace_policy.mode.value
                if workspace_policy.value_limit is not None:
                    value_limit = workspace_policy.value_limit
            finally:
                session.close()

        def run() -> ActionDecision:
            return action_service.propose(
                proposal,
                x_reality_role,
                x_reality_tenant,
                workspace_mode=workspace_mode,
                order_value=order_value_for(x_reality_tenant, proposal.target_entity),
                value_limit=value_limit,
            )

        if app_settings.persistence_enabled:
            session = make_session()
            try:
                restore_actions(x_reality_tenant, session)
                decision = run()
                persist_action_events(x_reality_tenant, decision.action_id, session)
                session.commit()
                return decision
            finally:
                session.close()
        return run()

    @app.post("/v1/actions/{action_id}/approve", response_model=ActionDecision)
    def approve_action(
        action_id: str,
        approval: ApprovalRequest,
        x_reality_role: str = Header(default="observer"),
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                restore_actions(x_reality_tenant, session)
                decision = approve_action_impl(
                    action_id, approval, x_reality_role, x_reality_tenant
                )
                persist_action_events(x_reality_tenant, action_id, session)
                session.commit()
                session.close()
                return decision
            return approve_action_impl(action_id, approval, x_reality_role, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/actions/{action_id}", response_model=ActionStatusResponse)
    def action_status(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionStatusResponse:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    restore_actions(x_reality_tenant, session)
                finally:
                    session.close()
            events = action_service.events(action_id, x_reality_tenant)
            decision = action_service.get_decision(action_id, x_reality_tenant)
            return ActionStatusResponse(decision=decision, events=events)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def approve_action_impl(
        action_id: str,
        approval: ApprovalRequest,
        x_reality_role: str,
        x_reality_tenant: str,
    ) -> ActionDecision:
        try:
            action = action_service.get_proposal(action_id, x_reality_tenant)
            order_id = action.target_entity.removeprefix("order:")
            current_state = resolve_order_state(x_reality_tenant, order_id)
            return action_service.approve(
                action_id,
                approval,
                x_reality_role,
                x_reality_tenant,
                current_state,
            )
        except KeyError:
            raise

    @app.post("/v1/actions/{action_id}/reject", response_model=ActionDecision)
    def reject_action(
        action_id: str,
        rejection: ApprovalRequest,
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    restore_actions(x_reality_tenant, session)
                    decision = action_service.reject(action_id, rejection, x_reality_tenant)
                    persist_action_events(x_reality_tenant, action_id, session)
                    session.commit()
                    return decision
                finally:
                    session.close()
            return action_service.reject(action_id, rejection, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/actions/{action_id}/execute", response_model=ExecutionReceipt)
    def execute_action(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> ExecutionReceipt:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    restore_actions(x_reality_tenant, session)
                finally:
                    session.close()
            proposal = action_service.get_proposal(action_id, x_reality_tenant)
            order_id = proposal.target_entity.removeprefix("order:")
            current_state = resolve_order_state(x_reality_tenant, order_id)
            receipt = action_service.execute(
                action_id,
                x_reality_tenant,
                shopify_connector.cancel_order,
                current_state,
            )
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    persist_action_events(x_reality_tenant, action_id, session)
                    session.commit()
                finally:
                    session.close()
            return receipt
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/actions/{action_id}/verify", response_model=ActionDecision)
    def verify_action(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    restore_actions(x_reality_tenant, session)
                finally:
                    session.close()
            proposal = action_service.get_proposal(action_id, x_reality_tenant)
            order_id = proposal.target_entity.removeprefix("order:")
            observed = shopify_connector.read_order(order_id)
            observation = shopify_connector.normalize(observed)
            state = world_state_service.ingest(
                x_reality_tenant,
                observation,
                cause="verified_action",
                assurance_level="verified",
            )
            decision = action_service.verify(action_id, x_reality_tenant, state)
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    persist_action_events(x_reality_tenant, action_id, session)
                    session.commit()
                finally:
                    session.close()
            return decision
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/actions/{action_id}/proof", response_model=ProofBundle)
    def action_proof(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> ProofBundle:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    restore_actions(x_reality_tenant, session)
                finally:
                    session.close()
            events = action_service.events(action_id, x_reality_tenant)
            commit_id: str | None = None
            for event in events:
                if event.event_type in {"verified", "state_diverged"}:
                    candidate = event.payload.get("commit_id")
                    if isinstance(candidate, str):
                        commit_id = candidate
            commit: CommitRecord | None = None
            if commit_id is not None:
                try:
                    commit = resolve_commit(x_reality_tenant, commit_id)
                except KeyError:
                    commit = None
            return action_service.proof(action_id, x_reality_tenant, commit=commit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/actions/{action_id}/events", response_model=list[ActionEventRecord])
    def action_events(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[ActionEventRecord]:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    events = ActionEventPersistenceService(session).list_for_action(
                        x_reality_tenant, action_id
                    )
                finally:
                    session.close()
                for event in events:
                    action_service.restore(event)
            return action_service.events(action_id, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
