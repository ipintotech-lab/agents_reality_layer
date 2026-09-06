# Reality Layer — MVP Design Doc

**Status:** Draft for review · **Owner:** ipintotech-lab · **Date:** 2026-09-06
**Companion doc:** [`reality-layer-technical-architecture.md`](./reality-layer-technical-architecture.md)

> This document turns the v2.0 technical architecture into a buildable MVP. It defines the
> smallest end-to-end slice that proves the core thesis: *agents act on a verified,
> permission-aware world state, and every change is auditable.* **No implementation yet —
> this is the plan.**

---

## 1. Goal and Non-Goals

### 1.1 MVP thesis

Prove one full loop for a single vertical (Order-to-Cash):

```
real source  →  immutable observation  →  compile  →  World State + commit
     →  agent reads state  →  proposes typed action  →  policy decision
     →  (optional HITL approval)  →  execute with idempotency
     →  verify externally (read-after-write)  →  new commit + proof bundle
```

### 1.2 In scope

| Area | MVP scope |
| --- | --- |
| Vertical | Order-to-Cash / supply operations only |
| Connectors | 1 commerce source (Shopify), 1 carrier (e.g. UPS/EasyPost), 1 DB/ERP source (Postgres or CSV) |
| Compiler | ingest → normalize/map → deterministic entity resolution → basic conflict detection → confidence + freshness → change detection → commit |
| Reality Git | append-only commits, entity-level diff, provenance links, snapshot reference, hash chain (no signatures) |
| Store | single PostgreSQL instance (relational + JSONB) + object storage for raw payloads |
| Policy/HITL | RBAC role templates (Operations, Support, Finance) + risk/cost thresholds + durable approval state machine |
| Actions | 1 real verified write operation end-to-end; 4–6 additional typed proposal/policy demos (see §6) |
| Interfaces | Python SDK, REST API, MCP server exposing the 6 core tools |
| Dashboard | read-only World State UI plus controlled operator workflows: Conflicts, Agents, Approvals, History, Health |
| Onboarding | `reality init` → Observe-only workspace, connector read checks, bounded backfill, data-quality report |

### 1.3 Explicitly NOT in MVP

- Graph database, multi-region, cross-party notarization, cryptographic signatures.
- ABAC, visual policy builder, Python policy SDK, policy-as-code CI.
- Agent simulation branches / merge of proposed future state.
- Verticals other than Order-to-Cash; community domain packs.
- Autonomous (unattended) execution tier — MVP stops at Approve.
- Self-hosted packaging polish (same interfaces, but managed-first).
- Fine-grained attribute-level encryption/tokenization (redaction only).

## 2. Success Criteria (exit checklist)

The MVP is "done" when, on a live investor-demo workspace:

1. Three real connectors ingest observations; World State compiles and is queryable.
2. An agent (LangGraph or Claude Agent SDK) reads state via MCP and proposes ≥3 of the
   action types.
3. Policy engine returns `allowed` / `approval_required` / `denied` with a machine-readable
   reason for each.
4. One write action runs end-to-end: it requires HITL, is approved through the operator
   workflow, executes, and is externally verified via read-after-write.
5. Every state transition has a commit linked to actor, cause, evidence, and
   `schema_version`; the History view shows before/after diffs.
6. A conflict (e.g. carrier says shipped, ERP says processing) appears in the conflict
   queue with side-by-side evidence and a controlled resolution workflow.
7. A `get_proof` call returns a proof bundle with an explicit assurance level.
8. Baseline metrics (§10) are recorded for the demo period.

## 3. Architecture (MVP shape)

Single deployable backend (modular monolith) + worker + web UI.

```
┌───────────────────────────────────────────────────────────────┐
│                        Agent (LangGraph / Claude Agent SDK)     │
└───────────────┬───────────────────────────────────────────────┘
                │ MCP tools / REST / Python SDK
┌───────────────▼───────────────────────────────────────────────┐
│  reality-api  (FastAPI)                                        │
│   ├─ Agent Interface (get_world_state, query_entities, ...)     │
│   ├─ Policy & Permission Engine (RBAC + risk/cost)             │
│   ├─ Action Gateway + Verifier                                 │
│   └─ Dashboard BFF (read-only state + workflow controls)       │
└───────┬───────────────────────────────┬───────────────────────┘
        │                               │
┌───────▼─────────┐            ┌─────────▼─────────────────────┐
│ reality-worker  │            │  PostgreSQL (+ JSONB)         │
│  ├─ Connectors  │            │   observation_log             │
│  │   (poll/hook)│            │   claim_store                 │
│  ├─ Compiler    │──writes──▶ │   entities / relations        │
│  │   pipeline   │            │   commit_log (hash chain)     │
│  └─ Verifier    │            │   action_ledger / approvals   │
│      jobs       │            │   outbox                      │
└───────┬─────────┘            └───────────────────────────────┘
        │
┌───────▼─────────┐
│ Object storage  │  raw payloads / large evidence
│ (S3-compatible) │
└─────────────────┘
```

**Rationale for a modular monolith:** the architecture doc calls for clean seams
(compiler stages, policy, gateway) but not independent scaling yet. Keep modules with
explicit interfaces so they can be split later; avoid distributed-systems overhead during
MVP.

### 3.1 Components

| Component | Responsibility | MVP tech |
| --- | --- | --- |
| `reality-api` | Agent interface, policy eval, action gateway, dashboard BFF | Python 3.12, FastAPI, Pydantic |
| `reality-worker` | Connector ingest, compiler pipeline, verifier jobs, outbox dispatch | Same codebase, background workers (Arq/Celery/APScheduler — TBD) |
| Store | Durable truth + projection | PostgreSQL 16, SQLAlchemy, Alembic; row-level tenant scoping |
| Object storage | Raw payloads, evidence | S3-compatible (MinIO local / Railway volume or bucket in prod) |
| `reality-mcp` | MCP server exposing 6 tools | thin adapter over the SDK/API |
| Dashboard | Read-only World State UI + approval/conflict workflow controls | Next.js (or server-rendered) — TBD, kept minimal |
| CLI | `reality init/connect/observe/serve` | Python (Typer) |

*Deployment:* Railway. **Requires a persistent volume for PostgreSQL and object storage —
ephemeral storage silently loses data.** Verify volume configuration before any DB
diagnosis.

## 4. Data Model (MVP tables)

All rows carry `tenant_id`. Append-only tables are enforced (no `UPDATE`/`DELETE` grants;
corrections are new rows).

| Table | Key columns | Mutability |
| --- | --- | --- |
| `observation_log` | `observation_id`, `tenant_id`, `source_id`, `connector_version`, `observed_at`, `received_at`, `payload_hash`, `payload_ref`, `schema_hint` | immutable |
| `claim_store` | `claim_id`, `entity_id`, `attribute`, `value` (JSONB), `source_refs`, `confidence`, `observed_at`, `expires_at`, `conflict_status` | append-only |
| `entities` | `entity_id`, `type`, `canonical_keys` (JSONB), `created_at` | identity stable; attrs via projection |
| `relations` | `from_entity`, `to_entity`, `type`, `confidence` | append-only + tombstone |
| `state_projection` | `entity_id`, `attributes` (JSONB), `confidence`, `freshness`, `provenance`, `conflicts`, `permissions`, `state_version` | rebuildable |
| `commit_log` | `commit_id`, `parent_ids`, `author`, `cause`, `message`, `diff` (JSONB), `provenance`, `action_ref`, `resulting_state_hash`, `prev_hash`, `schema_version` | immutable, hash-chained |
| `action_ledger` | `action_id`, `idempotency_key`, `proposed_by`, `action_type`, `target_entities`, `parameters_hash`, `preconditions`, `risk_score`, `cost_estimate`, `policy_decision`, `approval_ref`, `status`, `execution` (JSONB), `proof_ref` | append-only status history |
| `approvals` | `approval_ref`, `action_id`, `state`, `reviewer`, `rationale`, `scope`, `expires_at` | append-only state history |
| `outbox` | `event_id`, `event_type`, `payload`, `published_at` | append + mark published |

Envelopes for World State, Commit, Action Record, and Agent Activity Event follow §4 and
§16 of the architecture doc verbatim.

### 4.1 Reality Git commit envelope (MVP)

- `resulting_state_hash` = canonical hash of the affected entity projections after commit.
- `prev_hash` = `resulting_state_hash` of the parent commit → tamper-evident chain.
- Canonical JSON serialization (sorted keys, normalized numbers) defined once, shared by
  hashing and proof code. **No signatures in MVP**, but the serialization contract is
  frozen now.

## 5. Reality Compiler (MVP pipeline)

Incremental, triggered per observation batch; plus a nightly full reconciliation pass.

| Stage | MVP behavior | Deferred |
| --- | --- | --- |
| Ingest | Connector writes immutable observation + raw payload to object storage | streaming ingest |
| Normalize/map | Declarative connector mapping file (YAML) → canonical Order-to-Cash schema | learned mappings |
| Resolve entities | Deterministic keys only (order #, tracking #, SKU, email); ambiguous → review task | probabilistic matching |
| Conflict detection | Per entity+attribute: competing non-equal effective claims flagged | scoped/parallel-state claims |
| Conflict resolution | Policy: source priority → recency → confidence; else queue for human | auto-resolution learning |
| Confidence + freshness | `effective_confidence` formula (§7 arch doc); per-attribute decay config | corroboration graph dedupe of shared upstreams (basic only) |
| Change detection | Compare effective projection, not payload; semantic diff only | — |
| Publish | Atomic write of projection + commit + conflict tasks + outbox events | — |

Each stage is independently versioned (`compiler_version`) and replayable from
`observation_log`.

## 6. Actions (MVP set)

Investor-proof MVP separates depth from breadth:

- **Depth:** 1 real write action executes end-to-end with typed params, preconditions,
  idempotency key, HITL approval when required, read-after-write verification, commit, and
  proof bundle.
- **Breadth:** 4–6 additional high-value actions are implemented as typed proposals with
  policy decisions and demoable approval/risk rationale; they do not need production-grade
  external execution before investor-demo exit.

| Action | Target | Preconditions (example) | Verification | Default policy |
| --- | --- | --- | --- | --- |
| `cancel_order` | Order | `status in {pending, processing}` | re-read order status == `cancelled` | approval_required (Finance/Ops) |
| `update_shipping_address` | Order | `status == processing`, not yet handed to carrier | re-read address matches | approval_required if order value > threshold |
| `hold_order` / `release_order` | Order | order exists, not shipped/cancelled | re-read hold flag | allowed for Ops |
| `refund_order` (full/partial) | Order/Payment | `status in {shipped, delivered, cancelled}`, amount ≤ paid | provider refund receipt + re-read balance | approval_required (Finance) |
| `reship_order` | Order/Shipment | prior shipment `lost`/`damaged` confirmed by carrier claim | new shipment entity created + tracking # | approval_required |
| `update_inventory_adjustment` | Inventory | delta within blast-radius limit | re-read quantity == expected | allowed for Ops within budget |
| `notify_customer` (templated) | Customer | valid contact channel | provider send receipt | allowed |

"Verification" always means an independent observation, never just a 2xx response.

## 7. Policy & Permission Engine (MVP)

- **Model:** RBAC. Principals = `org → workspace → agent|user`. Roles: `operations`,
  `support`, `finance`, `admin`, `observer`.
- **Rule format:** YAML/JSON. Conditions on `action_type`, `entity.type`,
  `risk_score`, `cost_estimate`, `confidence`, `freshness`, `conflict_status`.
- **Outcomes:** `allowed` | `approval_required` | `denied` + `matched_rule` + reason
  string.
- **Safety defaults:** default-deny for all writes; new workspace = Observe-only; writes
  require explicit role + rule.
- **Evaluation:** pure function `(principal, proposal, pinned_state, policy_version) →
  decision`. Deterministic, unit-testable, versioned. Snapshot tests over a fixture
  library ship with MVP.
- **TOCTOU guard:** mutable preconditions re-checked against latest state immediately
  before execution.

Deferred: ABAC, relationship rules, simulation/counterfactual explanations, adaptive
approval, progressive trust automation.

## 8. HITL (MVP)

Durable state machine (not a blocking call). States from §10 of the architecture doc:
`pending_approval → approved | rejected | expired | superseded → executing → verified |
partial | failed`.

- Approval request payload includes proposed action, expected effect, world-state diff,
  evidence refs, risk, cost, confidence, policy reason, expiry, alternatives.
- Approvals are **scope-limited** (this action instance) and **time-limited** (expiry).
- State change to underlying entities between approval and execution → `superseded`,
  re-propose.
- Dashboard Approvals view = risk-ranked queue with impact preview.

## 9. Interfaces

### 9.1 MCP tools (the 6 core)

`get_world_state`, `query_entities`, `propose_action`, `get_action_status`, `get_proof`,
`diff_since` — semantics per §13.1 of the architecture doc. All responses
permission-filtered and annotated with freshness + confidence.

### 9.2 REST API

Thin HTTP mirror of the SDK: `GET /world-state`, `GET /entities`, `POST /actions`,
`GET /actions/{id}`, `GET /proofs/{action_id}`, `GET /diff?since=`, plus dashboard-only
read endpoints for conflicts, approvals, history, health.

### 9.3 Python SDK

`RealityClient` per §13.2. Auth: signed JWT or mTLS workload identity — **no shared agent
API keys in production** (static key allowed only for local dev).

### 9.4 CLI

`reality init` · `reality connect <source>` · `reality observe` · `reality serve --mcp`.

## 10. Metrics (instrument from day one)

| Metric | How measured in MVP |
| --- | --- |
| Prevented unsafe action rate | count of `denied` + `approval_required→rejected` / total proposals |
| Verification coverage | executed actions with conclusive postcondition + evidence bundle / all executed |
| World-state freshness | % of action-relevant claims within per-attribute freshness SLO |
| Conflict resolution time | median(resolved_at − detected_at) |
| Audit completeness | % commits with actor + cause + evidence + schema_version all populated |
| Decision latency | P50/P95 for read, propose-eval, approval, execute, verify |
| Trust progression | workspace stage transitions Observe→Propose→Approve |

## 11. Security & Isolation (MVP baseline)

- JWT/mTLS auth; per-agent identity.
- `tenant_id` mandatory in every storage key, query filter, queue message, log line, and
  proof; Postgres row-level security on tenant tables.
- Connector credentials in a vault/secret store, never returned to agents or the
  dashboard.
- Append-only commits and action records; corrections = new rows.
- Redaction of sensitive attributes in agent-facing responses (no tokenization yet).
- Abuse controls: per-workspace rate limits, per-action-type budgets, blast-radius caps,
  emergency "freeze workspace" switch.

## 12. Schema / Ontology (MVP boundary)

Compact Order-to-Cash domain pack: ~10–20 entity types, ~30–50 relationships. Candidate
entities: `Order`, `OrderLine`, `Shipment`, `Package`, `Inventory`, `Product`/`SKU`,
`Invoice`, `Payment`, `Refund`, `Customer`, `Address`, `Carrier`, `Warehouse`,
`ReturnRequest`.

- Semantic-versioned, immutable schema releases; `schema_version` stamped on every
  observation, claim, commit, proposal, proof.
- Connector mapping files versioned separately with contract tests (sample payload →
  expected canonical entity).
- Add concepts only when a real connector/action/policy/conflict/dashboard needs them.

## 13. Build Plan (phased — not yet started)

| Phase | Deliverable | Proves |
| --- | --- | --- |
| 0 · Foundations | Repo scaffold, Postgres schema + Alembic, canonical JSON + hashing lib, tenant scoping, CI | ground rules frozen |
| 1 · Observe | 1 read connector (Shopify), ingest → observation_log, compiler ingest→map→resolve→score→project, `get_world_state` / `query_entities`, Observe-only onboarding + data-quality report | verified world state exists |
| 2 · History | `commit_log` + hash chain, change detection, `diff_since`, dashboard Reality + History views | auditability |
| 3 · Conflicts | 2nd + 3rd connectors, conflict detection + resolution policy, conflict queue UI, resolution commits | conflicts are first-class |
| 4 · Propose + Policy | Action envelopes, RBAC policy engine + fixtures, `propose_action`, `get_action_status`, dashboard Agents view | intent ≠ execution |
| 5 · HITL + Act + Verify | Durable approval state machine, Action Gateway, idempotency, 1 real write action end-to-end, verifier read-after-write, proof bundle + `get_proof`, Approvals UI | the full loop with explicit human control |
| 6 · Demo Breadth | Remaining 4–6 actions as typed proposal/policy demos, controlled conflict resolution workflow, MCP server packaging, metrics dashboard | investor narrative breadth |
| 7 · Harden | Security review, Railway deploy w/ persistent volume, demo data reset/runbook, latency and audit-completeness checks | demo-ready MVP |

## 14. Key Technical Decisions (MVP)

Follows §20 of the architecture doc:

| Area | MVP choice | Revisit when |
| --- | --- | --- |
| State storage | PostgreSQL + JSONB + object storage | measured graph traversal bottleneck |
| History | custom append-only commit model over event/claim tables | need cross-region / external notarization |
| Compilation | event-driven incremental + nightly reconciliation | source lacks deltas or sustained lag |
| Branches | single authoritative mainline; no simulation branches in MVP | concrete multi-workspace merge use case |
| Long-running actions | async state machine + polling/webhook verifier | provider-specific orchestration dominates |
| Schema | layered versioned ontology, controlled extensions | repeated customer friction |
| Cryptography | canonical hashes + chain links; **no signatures** | regulated / cross-party proof requirement |
| Deployment | Railway managed, modular monolith + worker, persistent volume | scale or isolation pressure |

## 15. Open Questions

1. Worker/queue choice (Arq vs Celery vs APScheduler) — depends on Railway constraints.
2. Carrier connector: direct UPS API vs aggregator (EasyPost/Shippo) for the MVP demo.
3. Dashboard: full Next.js app vs server-rendered minimal UI given MVP scope.
4. Object storage on Railway: bucket vs mounted volume.
5. Identity provider for JWT/mTLS in the managed MVP.
6. How much backfill history is "bounded" per connector (30 / 90 days?).
7. Does the MVP demo need a second agent to show cross-agent dedup, or defer §16 entirely?
