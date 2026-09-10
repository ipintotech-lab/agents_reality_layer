from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
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
from reality_layer.api.schemas import ConflictResolutionRequest, WorkspaceModeRequest
from reality_layer.config import Settings, get_settings
from reality_layer.connectors import ShopifyConnector
from reality_layer.connectors.observe import ObservedPayload
from reality_layer.connectors.onboarding import preflight_demo
from reality_layer.connectors.persistence import ObservationIngestionService
from reality_layer.db.models import ConnectorKind
from reality_layer.storage import LocalObjectStore
from reality_layer.workspaces import WorkspaceService
from reality_layer.world_state import (
    CommitRecord,
    CompilerPersistenceService,
    Conflict,
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

    def hydrate_persisted_state(
        tenant_id: str, entity_id: str, compiler: CompilerPersistenceService
    ) -> OrderState | None:
        existing = compiler.load_state(tenant_id, entity_id)
        if existing is None:
            return None
        previous_commit = (
            compiler.load_commit(tenant_id, existing.commit_id)
            if existing.commit_id
            else None
        )
        world_state_service.hydrate(
            existing,
            existing.commit_id,
            previous_commit.hash if previous_commit else None,
        )
        return existing

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/preflight")
    def live_preflight(
        order_id: str | None = None,
        shipment_id: str | None = None,
    ) -> dict[str, object]:
        """Return sanitized live-demo connector and target eligibility checks."""
        return preflight_demo(app_settings, order_id, shipment_id)

    @app.get("/v1/connectors")
    def connector_status(
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[dict[str, object]]:
        if not app_settings.persistence_enabled:
            return []
        session = make_session()
        try:
            return [
                {
                    "connector_id": status.connector_id,
                    "kind": status.kind,
                    "display_name": status.display_name,
                    "capabilities": status.capabilities,
                    "last_check": status.last_check,
                }
                for status in WorkspaceService(session).connector_statuses(x_reality_tenant)
            ]
        finally:
            session.close()

    @app.get("/v1/workspace")
    def workspace_view(
        x_reality_tenant: str = Header(default="demo"),
    ) -> dict[str, object]:
        if not app_settings.persistence_enabled:
            return {
                "tenant_id": x_reality_tenant,
                "mode": app_settings.workspace_mode,
                "persistent": False,
                "write_value_limit": app_settings.write_value_limit,
            }
        session = make_session()
        try:
            policy = WorkspaceService(session).policy(x_reality_tenant)
        finally:
            session.close()
        return {
            "tenant_id": x_reality_tenant,
            "mode": policy.mode.value,
            "persistent": True,
            "write_value_limit": policy.value_limit,
        }

    @app.post("/v1/workspace/mode")
    def set_workspace_mode(
        request: WorkspaceModeRequest,
        x_reality_tenant: str = Header(default="demo"),
        x_reality_role: str = Header(default="observer"),
    ) -> dict[str, object]:
        if x_reality_role not in {"operations", "admin", "system"}:
            raise HTTPException(
                status_code=403,
                detail="Only operations, admin, or system may change the workspace mode.",
            )
        if not app_settings.persistence_enabled:
            raise HTTPException(
                status_code=409,
                detail="Workspace mode is not persistent; set REALITY_PERSISTENCE_ENABLED=true.",
            )
        session = make_session()
        try:
            bootstrap = WorkspaceService(session).set_mode(x_reality_tenant, request.mode)
            session.commit()
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            session.close()
        return {"tenant_id": x_reality_tenant, "mode": bootstrap.mode.value, "persistent": True}

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

    def list_world_state(
        tenant_id: str,
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
    ) -> list[OrderState]:
        if app_settings.persistence_enabled:
            session = make_session()
            try:
                states = CompilerPersistenceService(session).list_states(
                    tenant_id,
                    entity_type,
                    state,
                    freshness,
                    min_confidence,
                )
            finally:
                session.close()
            if states:
                return states
        return world_state_service.list_entities(
            tenant_id, entity_type, state, freshness, min_confidence
        )

    @app.get("/v1/world-state", response_model=list[OrderState])
    def get_world_state(
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[OrderState]:
        return list_world_state(
            x_reality_tenant, entity_type, state, freshness, min_confidence
        )

    @app.get("/v1/entities", response_model=list[OrderState])
    def list_entities(
        entity_type: str | None = None,
        state: str | None = None,
        freshness: str | None = None,
        min_confidence: float | None = None,
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[OrderState]:
        return list_world_state(
            x_reality_tenant, entity_type, state, freshness, min_confidence
        )

    @app.get("/v1/entities/{entity_type}/{entity_id}", response_model=OrderState)
    def get_entity(
        entity_type: str,
        entity_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        if entity_type not in {"order", "shipment"}:
            raise HTTPException(status_code=404, detail=f"Unknown entity type: {entity_type}")
        try:
            if app_settings.persistence_enabled:
                session = make_session()
                try:
                    state = CompilerPersistenceService(session).load_state(
                        x_reality_tenant, f"{entity_type}:{entity_id}"
                    )
                finally:
                    session.close()
                if state is not None:
                    return state
            return world_state_service.get_entity(x_reality_tenant, entity_type, entity_id)
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

    def has_conflict_for(tenant_id: str, target_entity: str) -> bool:
        entity_type, _, entity_id = target_entity.partition(":")
        if not entity_id:
            return False
        return world_state_service.has_open_conflicts(tenant_id, entity_type, entity_id)

    @app.get("/v1/conflicts", response_model=list[Conflict])
    def list_conflicts(
        status: str | None = None,
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[Conflict]:
        return world_state_service.list_conflicts(x_reality_tenant, status)

    @app.get("/v1/conflicts/{conflict_id}", response_model=Conflict)
    def get_conflict(
        conflict_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> Conflict:
        try:
            return world_state_service.get_conflict(x_reality_tenant, conflict_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/conflicts/{conflict_id}/resolve", response_model=Conflict)
    def resolve_conflict(
        conflict_id: str,
        request: ConflictResolutionRequest,
        x_reality_tenant: str = Header(default="demo"),
        x_reality_role: str = Header(default="observer"),
    ) -> Conflict:
        if x_reality_role not in {"operations", "admin", "system"}:
            raise HTTPException(
                status_code=403,
                detail="Only operations, admin, or system may resolve a conflict.",
            )
        try:
            return world_state_service.resolve_conflict(
                x_reality_tenant,
                conflict_id,
                request.resolved_value,
                x_reality_role,
                request.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
                has_conflict=has_conflict_for(x_reality_tenant, proposal.target_entity),
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

    @app.get("/v1/actions", response_model=list[ActionDecision])
    def list_actions(
        x_reality_tenant: str = Header(default="demo"),
    ) -> list[ActionDecision]:
        if app_settings.persistence_enabled:
            session = make_session()
            try:
                restore_actions(x_reality_tenant, session)
            finally:
                session.close()
        return action_service.list_actions(x_reality_tenant)

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
                    if not WorkspaceService(session).has_capability(
                        x_reality_tenant, ConnectorKind.shopify, "write"
                    ):
                        raise ValueError(
                            "Shopify write capability is not enabled for this workspace."
                        )
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
            session: Session | None = None
            if app_settings.persistence_enabled:
                session = make_session()
                if not WorkspaceService(session).has_capability(
                    x_reality_tenant, ConnectorKind.shopify, "read"
                ):
                    raise ValueError(
                        "Shopify read capability is not enabled for this workspace."
                    )
                restore_actions(x_reality_tenant, session)
            proposal = action_service.get_proposal(action_id, x_reality_tenant)
            order_id = proposal.target_entity.removeprefix("order:")
            observed = shopify_connector.read_order(order_id)
            observation = shopify_connector.normalize(observed)
            if session is None:
                state = world_state_service.ingest(
                    x_reality_tenant,
                    observation,
                    cause="verified_action",
                    assurance_level="verified",
                )
            else:
                stored = object_store.put_raw_payload(
                    x_reality_tenant,
                    observation.model_dump_json().encode(),
                    "application/json",
                )
                persisted = ObservationIngestionService(session).persist(
                    x_reality_tenant, ObservedPayload(observation, stored)
                )
                compiler = CompilerPersistenceService(session)
                hydrate_persisted_state(
                    x_reality_tenant,
                    f"{observation.object_type}:{observation.object_id}",
                    compiler,
                )
                state = world_state_service.ingest(
                    x_reality_tenant,
                    observation,
                    cause="verified_action",
                    assurance_level="verified",
                )
                if persisted.created:
                    compiler.persist(
                        state, world_state_service.get_commit_for_state(
                            x_reality_tenant, state
                        )
                    )
            decision = action_service.verify(action_id, x_reality_tenant, state)
            if session is not None:
                persist_action_events(x_reality_tenant, action_id, session)
                session.commit()
            return decision
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            if session is not None:
                session.close()

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

    dashboard_html = (Path(__file__).parent / "dashboard.html").read_text()

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return dashboard_html

    return app


app = create_app()
