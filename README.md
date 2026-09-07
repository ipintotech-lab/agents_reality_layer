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

Phase 0 foundation implementation started. The current codebase contains the initial Python
package scaffold, API health endpoint, database model/migration foundation, and Reality Git
canonical hashing utilities.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
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
