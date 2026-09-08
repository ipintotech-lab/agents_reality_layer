from pathlib import Path
from typing import Annotated, cast

import typer

from reality_layer import __version__
from reality_layer.config import get_settings
from reality_layer.connectors import (
    EasyPostConnector,
    EasyPostHttpClient,
    ShopifyConnector,
    ShopifyHttpClient,
)
from reality_layer.connectors.observe import Normalizer, observe_payload
from reality_layer.connectors.onboarding import (
    check_connectors,
    preflight_connectors,
    validate_demo_order,
)
from reality_layer.connectors.persistence import ObservationIngestionService
from reality_layer.db.models import ConnectorKind
from reality_layer.storage import LocalObjectStore
from reality_layer.workspaces import WorkspaceService
from reality_layer.world_state import (
    CompilerPersistenceService,
    OrderState,
    StateAttribute,
    WorldStateService,
)

app = typer.Typer(help="Reality Layer command line tools.")


def _emit_observations(
    tenant: str,
    payloads: list[dict[str, object]],
    normalizer: Normalizer,
    store: LocalObjectStore,
) -> None:
    for payload in payloads:
        observed = observe_payload(tenant, payload, normalizer, store)
        typer.echo(
            f"{observed.observation.observation_id}: "
            f"{observed.observation.object_type}:{observed.observation.object_id} "
            f"raw={observed.raw_payload.ref}"
        )


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show the installed version."),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init(
    tenant: str = typer.Option("demo", help="Tenant identifier."),
    workspace: str | None = typer.Option(None, help="Optional workspace identifier."),
) -> None:
    """Initialize an observe-only workspace and connector configuration."""
    settings = get_settings()
    if not settings.persistence_enabled:
        typer.echo(
            "Persistence is disabled; set REALITY_PERSISTENCE_ENABLED=true "
            "to initialize a durable workspace.",
            err=True,
        )
        raise typer.Exit(code=2)
    from reality_layer.db.session import SessionLocal

    session = SessionLocal()
    try:
        created = WorkspaceService(session).initialize(tenant, workspace)
        session.commit()
    except (RuntimeError, ValueError, OSError) as exc:
        session.rollback()
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()
    typer.echo(
        f"Initialized workspace {created.workspace_id} for tenant {created.tenant_id} "
        f"in {created.mode.value} mode; connectors={','.join(created.connector_ids)}"
    )


@app.command()
def workspace(
    tenant: str = typer.Option("demo", help="Tenant identifier."),
    mode: str | None = typer.Option(
        None, help="Set the workspace mode: observe_only or demo_proposal."
    ),
) -> None:
    """Show or set the workspace mode (the operator gate for agent write proposals)."""
    settings = get_settings()
    if not settings.persistence_enabled:
        typer.echo(
            "Persistence is disabled; workspace mode is governed by "
            f"REALITY_WORKSPACE_MODE={settings.workspace_mode!r}.",
            err=True,
        )
        raise typer.Exit(code=2)

    from reality_layer.db.models import WorkspaceMode
    from reality_layer.db.session import SessionLocal
    from reality_layer.workspaces import WorkspaceService

    session = SessionLocal()
    try:
        service = WorkspaceService(session)
        if mode is None:
            policy = service.policy(tenant)
            typer.echo(f"{tenant}: mode={policy.mode.value}")
            return
        try:
            target = WorkspaceMode(mode)
        except ValueError as exc:
            typer.echo(f"Unknown mode: {mode!r}", err=True)
            raise typer.Exit(code=2) from exc
        bootstrap = service.set_mode(tenant, target)
        session.commit()
        typer.echo(f"{tenant}: mode set to {bootstrap.mode.value}")
    except ValueError as exc:
        session.rollback()
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()


@app.command()
def connect(
    connector: Annotated[
        list[str], typer.Argument(help="Connector names to check: shopify and/or easypost.")
    ],
    tenant: str = typer.Option("demo", help="Tenant identifier."),
) -> None:
    """Validate configured connector access without printing credentials."""
    settings = get_settings()
    try:
        results = check_connectors(connector, settings)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    for result in results:
        status = "ok" if result["authenticated"] else "failed"
        typer.echo(
            f"{result['connector']}: {status}; "
            f"read={result['read_capability']}; write={result['write_capability']}"
        )
        if result["error"]:
            typer.echo(f"  error: {result['error']}", err=True)
    if settings.persistence_enabled:
        from reality_layer.db.session import SessionLocal

        session = SessionLocal()
        try:
            WorkspaceService(session).record_connector_checks(tenant, results)
            session.commit()
        except (RuntimeError, ValueError, OSError) as exc:
            session.rollback()
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        finally:
            session.close()
    if not all(bool(result["authenticated"]) for result in results):
        raise typer.Exit(code=1)


@app.command()
def preflight(
    tenant: str = typer.Option("demo", help="Tenant identifier."),
    order_id: str | None = typer.Option(
        None, "--order-id", help="Shopify test order ID to validate for cancellation."
    ),
) -> None:
    """Check all connector capabilities required for the live MVP demo."""
    import json

    settings = get_settings()
    try:
        result = preflight_connectors(settings)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if order_id is not None:
        connectors = cast(list[dict[str, object]], result["connectors"])
        shopify_result = next(
            connector
            for connector in connectors
            if connector["connector"] == "shopify"
        )
        if shopify_result["authenticated"] and shopify_result["read_capability"]:
            try:
                order = ShopifyHttpClient(
                    settings.shopify_domain, settings.shopify_access_token
                ).read_order(order_id)
                order_check = validate_demo_order(order, order_id)
            except (RuntimeError, ValueError, OSError) as exc:
                order_check = {
                    "eligible": False,
                    "order_id": order_id,
                    "failures": ["order.read_failed"],
                    "error": str(exc),
                }
        else:
            order_check = {
                "eligible": False,
                "order_id": order_id,
                "failures": ["order.connector_unavailable"],
            }
        result["demo_order"] = order_check
        if not bool(order_check["eligible"]):
            result["ready"] = False
            failures = cast(list[str], result["failures"])
            result["failures"] = [*failures, *cast(list[str], order_check["failures"])]

    if settings.persistence_enabled:
        from reality_layer.db.session import SessionLocal

        session = SessionLocal()
        try:
            WorkspaceService(session).record_connector_checks(
                tenant, result["connectors"]  # type: ignore[arg-type]
            )
            session.commit()
        except (RuntimeError, ValueError, OSError) as exc:
            session.rollback()
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        finally:
            session.close()

    typer.echo(json.dumps(result, indent=2, sort_keys=True))
    if not result["ready"]:
        raise typer.Exit(code=1)


@app.command()
def observe(
    connector: Annotated[str, typer.Argument(help="Connector to observe: shopify or easypost.")],
    tenant: str = typer.Option("demo", help="Tenant identifier."),
    limit: int = typer.Option(10, min=1, max=100, help="Maximum records to read."),
    persist: bool = typer.Option(False, help="Persist observation metadata to PostgreSQL."),
) -> None:
    """Read a bounded batch, retain raw payloads, and emit normalized observations."""
    settings = get_settings()
    store = LocalObjectStore(Path(settings.object_storage_root))
    session = None
    try:
        if persist:
            from reality_layer.db.session import SessionLocal

        session = SessionLocal() if persist else None
        if session is not None and not WorkspaceService(session).has_capability(
            tenant, ConnectorKind(connector), "read"
        ):
            raise ValueError(
                f"{connector} read capability is not enabled for this workspace."
            )
        if connector == "shopify":
            shopify_client = ShopifyHttpClient(
                settings.shopify_domain, settings.shopify_access_token
            )
            payloads = shopify_client.list_orders(limit)
            normalizer: Normalizer = ShopifyConnector()
        elif connector == "easypost":
            easypost_client = EasyPostHttpClient(settings.easypost_api_key)
            payloads = easypost_client.list_trackers(limit)
            normalizer = EasyPostConnector()
        else:
            raise ValueError(f"Unsupported connector: {connector}")
        ingestion = ObservationIngestionService(session) if session else None
        compiler = CompilerPersistenceService(session) if session else None
        world_state = WorldStateService()
        for payload in payloads:
            observed = observe_payload(tenant, payload, normalizer, store)
            if ingestion:
                persisted = ingestion.persist(tenant, observed)
                if persisted.created and compiler:
                    entity_id = (
                        f"{observed.observation.object_type}:{observed.observation.object_id}"
                    )
                    existing = compiler.projections.get(tenant, entity_id)
                    if existing:
                        previous_commit = (
                            compiler.commits.get(tenant, existing.producing_commit_id)
                            if existing.producing_commit_id
                            else None
                        )
                        hydrated = OrderState(
                            tenant_id=tenant,
                            entity_id=existing.entity_id,
                            entity_type=existing.entity_type,
                            state_version=existing.state_version,
                            attributes={
                                name: StateAttribute(
                                    value=value.get("value"),
                                    confidence=value.get("confidence", 0.0),
                                    observed_at=value["observed_at"],
                                    freshness=value["freshness"],
                                    source_observation_ids=value["source_observation_ids"],
                                )
                                for name, value in existing.attributes.items()
                            },
                            commit_id=existing.producing_commit_id or "",
                        )
                        world_state.hydrate(
                            hydrated,
                            existing.producing_commit_id,
                            previous_commit.hash if previous_commit else None,
                        )
                    state = world_state.ingest(tenant, observed.observation)
                    compiler.persist(state, world_state.get_commit_for_state(tenant, state))
            typer.echo(
                f"{observed.observation.observation_id}: "
                f"{observed.observation.object_type}:{observed.observation.object_id} "
                f"raw={observed.raw_payload.ref}"
            )
        if session:
            session.commit()
            session.close()
    except (OSError, RuntimeError, ValueError) as exc:
        if session:
            session.rollback()
            session.close()
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def verify(
    once: bool = typer.Option(
        False, help="Run a single verification sweep and exit instead of looping."
    ),
) -> None:
    """Run the read-after-write verifier worker."""
    from reality_layer.worker.main import build_worker

    worker = build_worker()
    if once:
        decisions = worker.run_once()
        for decision in decisions:
            typer.echo(f"{decision.action_id}: {decision.status} — {decision.reason}")
        return
    worker.run_forever()


@app.command()
def rehearse(
    tenant: str = typer.Option("demo", help="Tenant identifier for the local rehearsal."),
    order: str = typer.Option("rehearsal-order", help="Order identifier for the local rehearsal."),
    runs: int = typer.Option(
        1, min=1, max=100, help="Number of isolated rehearsals to execute."
    ),
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the proof JSON to this file.")
    ] = None,
    summary: bool = typer.Option(
        False, "--summary", help="Emit an operator-facing run summary instead of full proofs."
    ),
    fault: str = typer.Option(
        "none",
        "--fault",
        help="Inject a failure: none, provider_error, or verification_divergence.",
    ),
) -> None:
    """Run isolated complete MVP loops with the deterministic local Shopify adapter."""
    import json
    import time

    from reality_layer.rehearsal import (
        RehearsalFault,
        rehearsal_scenario_summary,
        rehearsal_summary,
        run_local_rehearsals,
        run_rehearsals,
    )

    try:
        injected = RehearsalFault(fault)
    except ValueError as exc:
        typer.echo(f"Unknown fault: {fault!r}", err=True)
        raise typer.Exit(code=2) from exc

    if injected is not RehearsalFault.none:
        try:
            started = time.perf_counter()
            results = run_rehearsals(tenant, order, runs, fault=injected)
            elapsed_seconds = time.perf_counter() - started
        except (RuntimeError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        scenario = rehearsal_scenario_summary(results, elapsed_seconds)
        typer.echo(json.dumps(scenario, indent=2, sort_keys=True))
        if not scenario["all_protected"]:
            typer.echo("Rehearsal did not fail safe for every run.", err=True)
            raise typer.Exit(code=1)
        return

    try:
        started = time.perf_counter()
        proofs = run_local_rehearsals(tenant, order, runs)
        elapsed_seconds = time.perf_counter() - started
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    payload = (
        rehearsal_summary(proofs, elapsed_seconds)
        if summary
        else proofs[0].model_dump(mode="json")
        if runs == 1
        else [proof.model_dump(mode="json") for proof in proofs]
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{rendered}\n", encoding="utf-8")
        typer.echo(f"Wrote rehearsal proof to {output}")
    else:
        typer.echo(rendered)


@app.command()
def demo(
    tenant: str = typer.Option("demo", help="Tenant identifier for the scripted demo."),
    order: str = typer.Option("demo-1001", help="Order identifier for the scripted demo."),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the happy-path proof bundle JSON here."),
    ] = None,
    proof: bool = typer.Option(
        False, "--proof", help="Print the proof bundle JSON instead of the transcript."
    ),
) -> None:
    """Run the scripted agent demo through the public MCP and REST contracts."""
    import json

    from reality_layer.demo import demo_transcript, run_agent_demo

    try:
        run = run_agent_demo(tenant, order)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(run.proof, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        typer.echo(f"Wrote proof bundle to {output}")

    if proof:
        typer.echo(json.dumps(run.proof, indent=2, sort_keys=True))
    else:
        typer.echo(demo_transcript(run))

    if not run.verified:
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
) -> None:
    import uvicorn

    uvicorn.run("reality_layer.api.app:app", host=host, port=port, reload=False)
