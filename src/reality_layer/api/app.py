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

    @app.get("/v1/commits/{commit_id}", response_model=CommitRecord)
    def get_commit(
        commit_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> CommitRecord:
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    commit = CompilerPersistenceService(session).load_commit(
                        x_reality_tenant, commit_id
                    )
                finally:
                    session.close()
                if commit is not None:
                    return commit
            return world_state_service.get_commit(x_reality_tenant, commit_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/actions", response_model=ActionDecision, status_code=201)
    def propose_action(
        proposal: ActionProposal,
        x_reality_role: str = Header(default="observer"),
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        if app_settings.persistence_enabled:
            session = make_session()
            try:
                restore_actions(x_reality_tenant, session)
                decision = action_service.propose(proposal, x_reality_role, x_reality_tenant)
                persist_action_events(x_reality_tenant, decision.action_id, session)
                session.commit()
                return decision
            finally:
                session.close()
        return action_service.propose(proposal, x_reality_role, x_reality_tenant)

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

    def approve_action_impl(
        action_id: str,
        approval: ApprovalRequest,
        x_reality_role: str,
        x_reality_tenant: str,
    ) -> ActionDecision:
        try:
            action = action_service.get_proposal(action_id, x_reality_tenant)
            order_id = action.target_entity.removeprefix("order:")
            try:
                current_state = world_state_service.get_order(x_reality_tenant, order_id)
            except KeyError:
                current_state = None
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
            return action_service.reject(action_id, rejection, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/actions/{action_id}/execute", response_model=ExecutionReceipt)
    def execute_action(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> ExecutionReceipt:
        try:
            return action_service.execute(
                action_id,
                x_reality_tenant,
                shopify_connector.cancel_order,
            )
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
            return action_service.verify(action_id, x_reality_tenant, state)
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
            return action_service.proof(action_id, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/actions/{action_id}/events", response_model=list[ActionEventRecord])
    def action_events(
        action_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[ActionEventRecord]:
        try:
            return action_service.events(action_id, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
