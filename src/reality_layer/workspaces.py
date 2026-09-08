from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reality_layer.db.models import Connector, ConnectorKind, Workspace, WorkspaceMode


@dataclass(frozen=True)
class WorkspaceBootstrap:
    workspace_id: str
    tenant_id: str
    mode: WorkspaceMode
    connector_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkspacePolicy:
    mode: WorkspaceMode
    value_limit: float | None


class WorkspaceService:
    """Creates the tenant-scoped workspace baseline without storing credentials."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def initialize(
        self,
        tenant_id: str,
        workspace_id: str | None = None,
        *,
        connector_kinds: tuple[ConnectorKind, ...] = (
            ConnectorKind.shopify,
            ConnectorKind.easypost,
        ),
    ) -> WorkspaceBootstrap:
        conditions = [Workspace.tenant_id == tenant_id]
        if workspace_id is not None:
            conditions.append(Workspace.workspace_id == workspace_id)
        existing = self.session.scalars(select(Workspace).where(*conditions)).first()
        if existing is not None:
            connectors = self.session.scalars(
                select(Connector).where(
                    Connector.tenant_id == tenant_id,
                    Connector.workspace_id == existing.workspace_id,
                )
            ).all()
            return WorkspaceBootstrap(
                existing.workspace_id,
                tenant_id,
                WorkspaceMode(existing.mode),
                tuple(connector.connector_id for connector in connectors),
            )

        identifier = workspace_id or f"ws_{uuid4().hex[:16]}"
        workspace = Workspace(
            workspace_id=identifier,
            tenant_id=tenant_id,
            mode=WorkspaceMode.observe_only,
            thresholds={},
            bounded_backfill={},
        )
        self.session.add(workspace)
        connector_ids: list[str] = []
        for kind in connector_kinds:
            connector_id = f"{identifier}_{kind.value}"
            self.session.add(
                Connector(
                    connector_id=connector_id,
                    tenant_id=tenant_id,
                    workspace_id=identifier,
                    kind=kind,
                    display_name=kind.value.title(),
                    capabilities={"read": False, "write": False},
                    required_scopes=[],
                    config_ref=f"settings:{kind.value}",
                    last_check={},
                )
            )
            connector_ids.append(connector_id)
        self.session.flush()
        return WorkspaceBootstrap(
            identifier,
            tenant_id,
            WorkspaceMode.observe_only,
            tuple(connector_ids),
        )

    def policy(self, tenant_id: str) -> WorkspacePolicy:
        workspace = self.session.scalars(
            select(Workspace)
            .where(Workspace.tenant_id == tenant_id)
            .order_by(Workspace.created_at.asc())
        ).first()
        if workspace is None:
            return WorkspacePolicy(WorkspaceMode.observe_only, None)
        raw_limit = workspace.thresholds.get("write_value_limit")
        try:
            value_limit = float(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError("Workspace write value limit must be numeric.") from exc
        return WorkspacePolicy(WorkspaceMode(workspace.mode), value_limit)

    def record_connector_checks(
        self, tenant_id: str, results: list[dict[str, object]]
    ) -> None:
        workspace = self.session.scalars(
            select(Workspace)
            .where(Workspace.tenant_id == tenant_id)
            .order_by(Workspace.created_at.asc())
        ).first()
        if workspace is None:
            raise ValueError(f"No workspace is initialized for tenant {tenant_id}.")
        connectors = {
            connector.kind: connector
            for connector in self.session.scalars(
                select(Connector).where(
                    Connector.tenant_id == tenant_id,
                    Connector.workspace_id == workspace.workspace_id,
                )
            ).all()
        }
        for result in results:
            name = result.get("connector")
            if not isinstance(name, str) or name not in connectors:
                raise ValueError(f"Connector is not configured for workspace: {name!r}.")
            connector = connectors[name]
            connector.capabilities = {
                "read": bool(result.get("read_capability")),
                "write": bool(result.get("write_capability")),
            }
            connector.last_check = {
                "authenticated": bool(result.get("authenticated")),
                "error": result.get("error"),
            }
        self.session.flush()
