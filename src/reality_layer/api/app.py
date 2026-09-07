from fastapi import FastAPI, Header, HTTPException

from reality_layer import __version__
from reality_layer.actions import ActionService
from reality_layer.actions.models import (
    ActionDecision,
    ActionEventRecord,
    ActionProposal,
    ApprovalRequest,
)
from reality_layer.world_state import CommitRecord, Observation, OrderState, WorldStateService


def create_app() -> FastAPI:
    app = FastAPI(title="Reality Layer", version=__version__)
    action_service = ActionService()
    world_state_service = WorldStateService()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/observations", response_model=OrderState, status_code=201)
    def ingest_observation(
        observation: Observation,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        return world_state_service.ingest(x_reality_tenant, observation)

    @app.get("/v1/orders/{order_id}", response_model=OrderState)
    def get_order(
        order_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        try:
            return world_state_service.get_order(x_reality_tenant, order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/shipments/{shipment_id}", response_model=OrderState)
    def get_shipment(
        shipment_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> OrderState:
        try:
            return world_state_service.get_entity(x_reality_tenant, "shipment", shipment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/commits/{commit_id}", response_model=CommitRecord)
    def get_commit(
        commit_id: str,
        x_reality_tenant: str = Header(default="demo"),
    ) -> CommitRecord:
        try:
            return world_state_service.get_commit(x_reality_tenant, commit_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/actions", response_model=ActionDecision, status_code=201)
    def propose_action(
        proposal: ActionProposal,
        x_reality_role: str = Header(default="observer"),
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        return action_service.propose(proposal, x_reality_role, x_reality_tenant)

    @app.post("/v1/actions/{action_id}/approve", response_model=ActionDecision)
    def approve_action(
        action_id: str,
        approval: ApprovalRequest,
        x_reality_role: str = Header(default="observer"),
        x_reality_tenant: str = Header(default="demo"),
    ) -> ActionDecision:
        try:
            return action_service.approve(action_id, approval, x_reality_role, x_reality_tenant)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
