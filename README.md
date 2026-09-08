# Reality Layer

A current, verified, permission-aware representation of the operational world for AI
agents — plus a controlled path from an agent's intent to an externally verified result.

Two core systems:

- **Reality Compiler** — turns raw observations and agent activity into structured, scored,
  queryable world state.
- **Reality Git** — append-only history, diffs, provenance, decisions, actions, and proofs
  of how that world changed.

Model-independent. Designed for LangGraph, CrewAI, Claude Agent SDK, MCP clients, and
custom orchestrators.

## Status

Investor MVP prototype in active development on the `verifier-worker` branch. The current
codebase contains a working Order-to-Cash control loop with tenant-scoped observations,
World State projections, typed action proposals, default-deny policy evaluation,
precondition revalidation, idempotent Shopify test-adapter execution, independent
read-after-write verification, hash-linked action/commit events, proof bundles, bounded
verifier-worker polling, and optional PostgreSQL persistence.

The following remain partial or planned: full conflict claims and resolution workflows,
field-level permission filtering and ABAC, durable HITL expiry/delegation/supersession,
the MCP adapter and SDK, complete workspace/connector persistence, live Shopify/EasyPost
validation, signed attestations, and dashboard/demo UI. REST is currently the canonical
active interface.

The product contract requires new workspaces to start in `observe_only` mode. The current
demo runtime uses an explicit `demo_proposal` configuration exception until durable
workspace initialization is complete.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

PostgreSQL persistence coverage is opt-in and expects a disposable database:

```bash
REALITY_TEST_DATABASE_URL=postgresql+psycopg://... pytest tests/integration
```

## Docs

| Doc | Purpose |
| --- | --- |
| [`docs/reality-layer-technical-architecture.md`](docs/reality-layer-technical-architecture.md) | Full v2.0 technical architecture |
| [`docs/mvp-design.md`](docs/mvp-design.md) | MVP scope, build plan, and technical decisions |

## MVP at a glance

One end-to-end loop for the Order-to-Cash vertical:

```
real source → immutable observation → compile → World State + commit
  → agent reads state → proposes typed action → policy decision
  → (optional HITL approval) → execute with idempotency
  → verify externally → new commit + proof bundle
```
