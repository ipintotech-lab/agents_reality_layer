# Reality Layer — Investor MVP

**Status:** Updated MVP · **Owner:** ipintotech-lab · **Date:** 2026-09-06  
**Scope authority:** This document supersedes the original broad MVP scope for the investor demo.  
**Companion document:** `reality-layer-technical-architecture.md`

### Implementation status

All nine build-plan phases (§15) are functionally complete against the local
fallback path; the remaining work is live-service validation and deployment
infrastructure that needs real credentials (see §15 for the exact list).

The repository currently contains a working MVP prototype for:

- tenant-scoped observations and World State projections;
- provenance, confidence, and freshness metadata;
- typed action proposals and default-deny policy evaluation;
- approval/rejection with precondition revalidation;
- idempotent Shopify test-adapter execution;
- independent read-after-write verification;
- hash-linked action events and commits;
- proof bundles and bounded verifier-worker polling;
- optional PostgreSQL persistence and restart-safe action event restoration;
- REST action status and semantic diff history endpoints;
- a read-only operator dashboard (World State, Approval, History/Proof) served at `/`;
- a scripted agent demo (`reality demo`) that drives the happy, policy-control, and
  proposal-only paths through the public MCP and REST contracts;
- durable workspace mode transitions (`observe_only` <-> `demo_proposal`) via the
  `reality workspace` CLI and the `GET /v1/workspace` / `POST /v1/workspace/mode`
  endpoints, role-gated to operations/admin/system;
- rehearsal fault injection (`reality rehearse --fault provider_error |
  verification_divergence`) with per-step latency capture, proving the loop
  reaches a protective terminal status instead of a false `verified`;
- repeatable local rehearsal tooling (`reality rehearse --runs N --summary`) with
  isolated per-run state and no manual database repair between runs.

The following are partial or planned rather than complete MVP capabilities:

- full competing-claim conflict detection and resolution workflows;
- field-level permission filtering and ABAC;
- durable HITL expiry, delegation, supersession, and scoped approvals;
- agent SDK and dashboard permission filtering / provenance drill-down;
- complete connector persistence and health-state surfacing;
- live Shopify/EasyPost behavior validation and a live dress rehearsal;
- Railway deployment with a persistent PostgreSQL volume;
- signed attestations or external notarization.

The product contract requires each new workspace to start in `observe_only` mode. With
persistence enabled, an operator moves the workspace to `demo_proposal` explicitly
(`reality workspace --mode demo_proposal` or `POST /v1/workspace/mode`) before an agent
may propose writes. Without persistence, the demo runtime falls back to an explicit
`REALITY_WORKSPACE_MODE` configuration setting.

> Build the smallest reliable system that proves an AI agent can act on a real business system without requiring the business to blindly trust either the agent or the API response.

---

## 1. Product thesis

AI agents can call APIs, but API access alone does not make their actions trustworthy. The Reality Layer maintains an observed, permission-aware World State and mediates agent actions through policy, human approval, idempotent execution, external verification, and auditable evidence.

The MVP must prove one complete loop:

```text
real source → immutable observation → compile → World State
     → agent reads state → proposes typed action → policy decision
     → HITL approval → idempotent execution
     → independent read-after-write verification → commit + proof bundle
```

The investor demo is not intended to prove broad connector coverage, autonomy, or production scale. It proves that one consequential agent action can be controlled and independently verified end to end.

---

## 2. MVP goals

The MVP must demonstrate that:

1. Data from two real systems can be converted into a queryable World State.
2. Every effective state change can be traced to immutable source observations.
3. An agent can propose typed actions but cannot bypass policy or approval.
4. A human can approve or reject a pending action.
5. One real write can be executed safely and idempotently.
6. Success is established through an independent read-after-write observation, not an API success response.
7. The system can produce a human-readable and machine-readable proof bundle.
8. The complete flow can be demonstrated reliably in three to four minutes.

---

## 3. Scope

### 3.1 Included

| Area | MVP scope |
|---|---|
| Business vertical | Order-to-Cash |
| Source systems | Shopify development store + EasyPost test environment |
| Connectors | Shopify orders and EasyPost shipment/tracking observations |
| World State | Orders and shipments with provenance, confidence, and freshness |
| Compiler | Ingest, normalize, deterministic resolution, scoring, projection, commit |
| Agent interface | REST API is implemented and canonical; thin MCP adapter remains planned |
| Policy | Default-deny writes, Observe-only workspace, RBAC templates, value/risk threshold |
| HITL | One authenticated approval or rejection step |
| Real action | `cancel_order` against a designated Shopify test order |
| Proposal-only actions | `update_shipping_address`, `hold_order` |
| Verification | Polling read-after-write against Shopify until success or timeout |
| Audit | Append-only observations, commits, action events, and hash chain |
| Dashboard | Planned; current MVP is API and worker focused |
| Storage | PostgreSQL 16 with JSONB; S3-compatible raw-payload storage |
| CLI | `reality init`, `reality connect`, `reality observe`, `reality serve` |

### 3.2 Explicitly excluded

- A third connector, ERP integration, database connector, or CSV ingestion
- Autonomous or unattended execution
- Production payment or refund processing
- Probabilistic entity resolution
- Full claim graph or graph database
- Advanced conflict-resolution queues and policies
- Multi-step approval, expiry, delegation, alternatives, or proposal supersession
- ABAC, a visual policy builder, or policy-as-code CI
- Cryptographic signatures or external timestamping
- Multi-region deployment or production-scale high availability
- Full CLI, Agents screen, Health screen, or Metrics dashboard
- Polished self-hosted distribution

---

## 4. Fixed MVP decisions

### 4.1 Interface

REST is the canonical contract. The MCP server is a thin adapter over the same application services and must not implement separate business logic.

This allows deterministic API tests while preserving an agent-native investor experience.

### 4.2 Connectors

The MVP uses:

- **Shopify:** system of record for orders and the target of the real write.
- **EasyPost:** shipping API aggregator used as the second observed source for shipment and tracking state.

Both connectors use isolated test/development environments. No production customer order is modified during the demo.

### 4.3 Real action

`cancel_order` is the only executable action. It operates only on a designated Shopify test order that:

- belongs to the current tenant;
- is unfulfilled;
- has not already been cancelled;
- does not require a real monetary refund;
- was created specifically for the current demo or rehearsal.

The exact Shopify cancel options are fixed in configuration and displayed to the approver. The MVP does not infer refund, restock, or customer-notification behavior.

### 4.4 Safety model

- A new workspace always starts in `observe_only` mode.
- All writes are default-denied unless an explicit policy matches.
- The demo operator must explicitly enable proposal/approval mode.
- Connector credentials are server-side and never exposed to the agent.
- The action gateway is the only component permitted to call write endpoints.

---

## 5. Primary demo scenario

### 5.1 Happy path

1. Shopify and EasyPost observations are ingested.
2. The compiler projects an order and its shipment into World State.
3. The dashboard shows source provenance, freshness, and confidence.
4. An agent queries the order and proposes `cancel_order`.
5. Policy returns `approval_required` because the action is a write and/or exceeds the configured threshold.
6. An Operations approver reviews the typed request, reason, evidence, and expected change.
7. The approver approves the proposal.
8. The gateway validates the current state and idempotency key, then calls Shopify.
9. The provider response is recorded as `provider_accepted`, but not treated as proof of success.
10. The verifier polls Shopify independently and ingests a new observation.
11. The compiler updates the projection and creates a commit.
12. The action becomes `verified`, and the dashboard presents the diff and proof bundle.

### 5.2 Policy-control path

The agent also proposes at least one action that is denied, such as:

- an `observer` attempting `cancel_order`; or
- `update_shipping_address` on an order above the permitted value threshold.

The dashboard/API displays the machine-readable policy rule and plain-language reason. No approval or execution path is created for a denied action.

### 5.3 Proposal-only path

The agent may propose `hold_order` or `update_shipping_address`. The policy decision is shown, but the MVP never executes these action types.

---

## 6. User roles

| Role | Capabilities |
|---|---|
| `observer` | Read permission-filtered World State, history, and proofs; cannot propose writes |
| `operations` | Read state, propose operational actions, approve or reject eligible operational actions |
| `finance` | Read financial order fields and review value-sensitive actions; cannot execute directly |
| `system` | Ingest, compile, execute approved actions, verify, and create commits |

For the investor demo, the proposer and approver may be the same authenticated operator only when `demo_mode` is explicitly enabled. The proof bundle records this as a demo exception. Production separation of duties is deferred.

---

## 7. Functional requirements

### 7.1 Workspace onboarding

`reality init` creates a tenant-scoped workspace with:

- mode set to `observe_only`;
- default-deny write policy;
- Operations, Finance, and Observer role templates;
- empty connector configuration;
- a generated workspace identifier;
- a bounded backfill configuration.

`reality connect` validates read access for Shopify and EasyPost. Shopify write access is checked separately and remains disabled until explicitly enabled.

Connector checks must report:

- authentication status;
- required scopes;
- read capability;
- write capability, where applicable;
- last successful check;
- actionable error details without leaking secrets.

### 7.2 Observation ingestion

Each source read produces an immutable observation containing:

- tenant and connector identity;
- external object type and identifier;
- source event/read timestamp;
- ingestion timestamp;
- raw payload reference;
- payload hash;
- connector/schema version;
- correlation identifier;
- ingest outcome.

Raw payloads are stored in S3-compatible object storage. PostgreSQL stores metadata and immutable references.

Duplicate source events must not create duplicate effective observations. Deduplication uses a connector-specific external event ID where available, otherwise a stable payload fingerprint.

### 7.3 Compiler

The compiler runs incrementally for each observation batch:

1. **Normalize:** Apply versioned YAML mappings to canonical Order and Shipment types.
2. **Resolve:** Match entities using deterministic keys only: Shopify order ID/order number and tracking number.
3. **Score:** Calculate confidence and freshness per projected attribute.
4. **Project:** Determine the effective tenant-scoped entity state.
5. **Detect change:** Compare the effective state with the current projection.
6. **Commit:** If the effective state changed, update the rebuildable projection and append an immutable commit.

The same ordered observation set and mapping version must produce the same effective projection and semantic diff.

### 7.4 Confidence and freshness

The MVP uses a transparent, deterministic formula rather than learned scoring.

Confidence is based on:

- source reliability configured per attribute;
- mapping completeness;
- identifier quality;
- whether another source provides compatible evidence.

Freshness is computed from the source observation time and an attribute-specific freshness window.

Every returned attribute must expose:

```json
{
  "value": "cancelled",
  "confidence": 0.98,
  "observed_at": "2026-09-06T12:00:00Z",
  "fresh_until": "2026-09-06T12:05:00Z",
  "freshness": "fresh",
  "source_observation_ids": ["obs_..."]
}
```

Scores must not imply stronger assurance than the available evidence. Full conflict adjudication is deferred; incompatible values are exposed as low-confidence state with source evidence, not silently hidden.

### 7.5 Querying World State

The API must support:

- fetching a permission-filtered snapshot;
- querying orders and shipments by deterministic identifiers;
- filtering by state, freshness, and minimum confidence;
- returning the commit ID that produced the snapshot;
- tracing projected attributes to source observations.

### 7.6 Typed action proposals

An action proposal includes:

- action type and schema version;
- tenant and target entity;
- typed parameters;
- actor and role;
- reason supplied by the agent;
- evidence and source commit ID;
- expected current state/version;
- expected outcome;
- requested timestamp;
- proposal correlation ID.

The server validates the action schema and target entity before policy evaluation. Free-form text is context only and cannot alter typed parameters.

### 7.7 Policy decisions

The policy engine returns exactly one outcome:

- `allowed`
- `approval_required`
- `denied`

Each decision records:

- matched policy and version;
- machine-readable reason code;
- human-readable explanation;
- evaluated attributes;
- decision timestamp;
- actor and role;
- required approver role, when applicable.

Example MVP rules:

| Rule | Outcome |
|---|---|
| Workspace is `observe_only` and action is a write | `denied` |
| Role is `observer` and action is a write proposal | `denied` |
| `cancel_order` by Operations for an eligible test order | `approval_required` |
| Order value is above configured Operations threshold | `approval_required` or `denied`, according to policy |
| Action type has no explicit policy | `denied` |

### 7.8 Approval

The Approval screen shows:

- target order and current state;
- proposed typed action;
- agent rationale and evidence;
- policy decision and reason;
- expected before/after state;
- important side effects configured for the Shopify call;
- Approve and Reject controls.

Approval is an authenticated append-only action event. Before execution, the gateway revalidates tenant, actor permission, target state, proposal version, and policy. An approval never directly invokes a connector from the browser.

### 7.9 Idempotent execution

The semantic idempotency key is:

```text
cancel_order:{tenant_id}:{shopify_order_id}:{expected_state_version}
```

The action gateway must guarantee that retries do not produce a second effective cancellation or duplicate side effect. A retry returns the existing action outcome when the same key has already been accepted or verified.

Before calling Shopify, the gateway checks:

- the action is approved;
- the current projection still matches the expected state/version;
- the target is an eligible test order;
- no successful or in-flight execution exists for the idempotency key;
- the connector write capability is enabled.

If the expected state has changed, execution stops with `precondition_failed` and must not call Shopify.

### 7.10 External verification

A successful write response changes the action state to `provider_accepted`; it does not mark the action successful.

The verifier:

1. waits for a short configurable interval;
2. reads the order from Shopify using a separate read operation;
3. ingests the response as a new immutable observation;
4. compiles the observation into World State;
5. compares the effective state with the action's expected outcome;
6. retries with bounded backoff until success or timeout.

Possible verification results:

- `verified`
- `verification_pending`
- `verification_failed`
- `state_diverged`

Only `verified` represents successful completion of the trustworthy loop.

### 7.11 Commits and diffs

A commit is created only when the effective World State changes. It contains:

```yaml
commit_id:
parent_commit_id:
tenant_id:
entity_type:
entity_id:
actor:
cause:
observation_ids:
action_id:
mapping_version:
before:
after:
semantic_diff:
assurance_level:
created_at:
previous_hash:
hash:
```

The hash is calculated from a canonical serialized representation of the commit. Signatures and external anchoring are deferred.

`diff_since` returns semantic entity and attribute changes rather than storage-level row differences.

### 7.12 Proof bundle

The proof bundle is available as JSON and in a human-readable dashboard view. It includes:

- action request and typed parameters;
- proposer and approver identities;
- policy decision and policy version;
- approval/rejection event;
- idempotency key;
- provider request fingerprint and redacted response evidence;
- verification observation;
- before/after projection and semantic diff;
- related commit and hash-chain references;
- timestamps and correlation IDs;
- explicit assurance level;
- warnings, including any demo-mode exception.

Assurance levels are:

| Level | Meaning |
|---|---|
| `observed` | State was read from an external source |
| `accepted` | The external provider accepted the write request |
| `verified` | The desired state was independently read back and compiled |
| `corroborated` | Multiple independent sources support the resulting state; reserved for later scope |

The successful investor flow must end at `verified`.

---

## 8. Action lifecycle

The action lifecycle is represented by immutable events:

```text
proposed
  → policy_evaluated
  → approval_requested
  → approved | rejected
  → execution_started
  → provider_accepted | execution_failed
  → verification_pending
  → verified | verification_failed | state_diverged
  → committed
```

Not every action follows every transition. A denied action ends after `policy_evaluated`; a rejected action ends at `rejected`.

Every event includes:

- event ID and action ID;
- tenant ID;
- event type and schema version;
- actor;
- timestamp;
- correlation ID;
- structured payload;
- evidence references;
- previous event hash and event hash.

`get_action_status` derives the current status from the latest valid event. Events are never overwritten.

---

## 9. Data model

All records include `tenant_id`. Tenant filtering is enforced server-side and is part of every repository query.

| Table | Purpose | Mutability |
|---|---|---|
| `workspace` | Tenant configuration, operating mode, thresholds | mutable configuration |
| `connector` | Connector metadata, capabilities, last check; no plaintext secrets | mutable configuration |
| `observation_log` | Immutable source observations and raw-payload references | append-only |
| `state_projection` | Current effective entity state | rebuildable |
| `commit_log` | World State history and semantic diffs | append-only |
| `action_event` | Complete proposal-to-verification lifecycle | append-only |
| `policy_version` | Versioned policy documents and hashes | append-only versions |

`state_projection` may be rebuilt entirely from observations, mapping versions, and deterministic compiler logic. The append-only logs are authoritative.

---

## 10. Architecture

The MVP is a modular monolith deployed as an API process and a worker process from the same codebase.

```text
Agent ──MCP adapter──┐
                    ├── REST application services
Dashboard ──REST────┘      ├── query service
                           ├── policy engine
                           ├── approval service
                           └── action gateway
                                      │
Worker ────────────────────────────────┤
  ├── Shopify connector               │
  ├── EasyPost connector              │
  ├── compiler                        │
  └── verifier                        │
                                      ▼
                              PostgreSQL + object storage
```

### 10.1 Technology choices

| Component | Technology |
|---|---|
| Runtime | Python 3.12 |
| API | FastAPI + Pydantic |
| Worker | Same Python package with database-backed jobs |
| Database | PostgreSQL 16 + JSONB |
| Raw payloads | S3-compatible object storage |
| Dashboard | Minimal Next.js UI or server-rendered equivalent |
| CLI | Typer |
| Agent integration | Thin MCP adapter over application services |

The MVP does not require Kafka, a graph database, Redis, Kubernetes, or microservices. Database-backed jobs and transactional writes are sufficient for the demo.

---

## 11. API and MCP contract

### 11.1 Canonical REST endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/v1/world-state` | Permission-filtered snapshot |
| `GET` | `/v1/entities` | Query orders and shipments |
| `GET` | `/v1/entities/{type}/{id}` | Entity state, freshness, confidence, provenance |
| `GET` | `/v1/diffs` | Semantic changes since a commit or timestamp |
| `POST` | `/v1/actions` | Submit a typed proposal and evaluate policy |
| `GET` | `/v1/actions/{id}` | Derived action status and event history |
| `POST` | `/v1/actions/{id}/approve` | Approve an eligible proposal |
| `POST` | `/v1/actions/{id}/reject` | Reject an eligible proposal |
| `GET` | `/v1/actions/{id}/proof` | Return proof bundle |

### 11.2 MCP tools

- `get_world_state`
- `query_entities`
- `propose_action`
- `get_action_status`
- `get_proof`
- `diff_since`

The MCP adapter authenticates to the same tenant and role model and calls the same application services as REST. It must not have direct database or connector access.

---

## 12. Dashboard

### 12.1 World State

Displays:

- order and shipment entities;
- effective state;
- source systems;
- attribute confidence and freshness;
- observation and commit timestamps;
- link to provenance and recent diff.

### 12.2 Approval

Displays:

- pending proposal;
- actor and rationale;
- typed parameters;
- supporting evidence;
- policy outcome and reason;
- expected change and configured side effects;
- Approve and Reject buttons.

### 12.3 History / Proof

Displays:

- commit chain;
- entity-level before/after diff;
- action event timeline;
- source and verification evidence;
- assurance badge;
- downloadable JSON proof bundle.

The dashboard is intentionally not an administration console. Connector setup may remain CLI/config driven.

---

## 13. Non-functional requirements

### 13.1 Reliability

- The live path must be rehearsable and resettable with a script or documented procedure.
- All external calls use bounded timeouts and retries.
- Verification uses bounded polling and shows pending state rather than blocking the UI.
- Duplicate webhooks, observations, approvals, and execution retries must be safe.

### 13.2 Performance targets

| Operation | Demo target |
|---|---|
| World State query | p95 under 500 ms excluding initial cold start |
| Proposal + policy decision | p95 under 750 ms |
| Approval acknowledgement | under 500 ms |
| Verified action completion | normally under 15 seconds; hard demo timeout 30 seconds |
| History/proof display | under 1 second |

### 13.3 Security

- Secrets are loaded from the runtime secret mechanism and never stored in logs or proof bundles.
- Raw payload access is tenant-scoped.
- Sensitive provider response fields are redacted before evidence is displayed.
- Writes require explicit connector scopes and gateway authorization.
- Every approval and execution event records an authenticated actor.
- The system rejects cross-tenant entity and action references.

### 13.4 Observability

Structured logs must include tenant ID, correlation ID, action ID, commit ID, connector, and stage. The demo runbook includes a single way to inspect failed ingest, execution, and verification jobs.

---

## 14. Acceptance criteria

Status (2026-09-08): every criterion below except live connector authentication
(14.1, first item) and the live dress rehearsal is exercised by the automated
suite and the local `reality rehearse` / `reality demo` paths. The checkboxes are
kept unchecked until each is confirmed once more against live Shopify/EasyPost
test environments during demo preflight.

### 14.1 Connectors and World State

- [ ] Shopify and EasyPost authenticate in isolated test environments.
- [ ] A bounded backfill ingests at least one linked order and shipment.
- [ ] Raw payloads are stored externally and referenced by immutable observations.
- [ ] Duplicate source delivery does not create a duplicate effective state change.
- [ ] World State returns provenance, confidence, freshness, and producing commit ID.

### 14.2 Compiler and history

- [ ] Deterministic identifiers resolve the demo Order and Shipment.
- [ ] Reprocessing the same observations produces the same projection.
- [ ] Effective changes create commits; no-op observations do not.
- [ ] `diff_since` returns a clear semantic before/after diff.
- [ ] The commit hash chain validates for the demo tenant.

### 14.3 Policy and HITL

- [ ] A new workspace is `observe_only`.
- [ ] An unauthorized write proposal is denied with a reason code.
- [ ] `cancel_order` returns `approval_required` for the configured scenario.
- [ ] The Approval screen shows typed parameters, evidence, policy reason, and side effects.
- [ ] Approval and rejection create immutable events.
- [ ] Policy and preconditions are rechecked immediately before execution.

### 14.4 Execution and verification

- [ ] Only the designated test-order cancellation can be executed.
- [ ] Reusing an idempotency key cannot duplicate the external effect.
- [ ] A stale expected state produces `precondition_failed` without a write call.
- [ ] A 2xx/provider success response produces `provider_accepted`, not `verified`.
- [ ] A separate Shopify read creates a verification observation.
- [ ] Matching read-back state produces `verified` and a resulting commit.
- [ ] Timeout and divergent-state paths are represented explicitly.

### 14.5 Proof and demo readiness

- [ ] The proof bundle links proposal, policy, approval, execution, verification, and commit.
- [ ] The successful proof ends with assurance level `verified`.
- [ ] Secrets and sensitive fields do not appear in the proof.
- [ ] The complete happy path runs in three to four minutes.
- [ ] The demo can be reset and repeated at least five times without manual database repair.
- [ ] A prerecorded fallback and static proof bundle are available if an external test service is unavailable.

---

## 15. Build plan

| Phase | Deliverables | Exit condition | Status |
|---|---|---|---|
| 0 — Foundation | Repository structure, local environment, tenant scoping, schema, object storage, CI | Tenant-isolation tests pass and append-only tables exist | Complete |
| 1 — Observe | Shopify/EasyPost connectors, bounded backfill, immutable observations, raw payload references | Two sources produce traceable observations | Complete (recorded fixtures; live behavior unvalidated) |
| 2 — Compile | Canonical schema, mappings, deterministic resolution, scoring, projection | Demo order/shipment are queryable with confidence and freshness | Complete |
| 3 — History | Commit creation, semantic diff, hash chain, History screen | World State changes are traceable to observations | Complete |
| 4 — Govern | Typed proposals, RBAC policies, thresholds, denial path, Approval screen | Agent intent is separated from authorized execution | Complete |
| 5 — Act | Shopify test cancellation, preconditions, semantic idempotency, append-only action events | Approved action executes at most once | Complete (deterministic test adapter) |
| 6 — Verify | Polling read-after-write, verification observation, proof bundle, assurance level | Full loop ends in `verified` | Complete |
| 7 — Integrate | MCP adapter, agent script, three-screen polish | Agent completes scripted demo through public contracts | Complete (`RealityMcpAdapter` for in-process use; `reality mcp-server` runs it as a real network MCP server over stdio/SSE/streamable-HTTP) |
| 8 — Rehearse | Seed/reset tooling, runbook, latency tests, failure injection, fallback recording | Five consecutive three-to-four-minute rehearsals succeed | Complete against the local fallback path; live-service dress rehearsal pending credentials |
| 9 — Conflicts (post-MVP) | Cross-source conflict detection on attribute merge, `Conflict`/`ConflictCandidate` model, policy gate denying proposals on conflicted entities, `GET/POST /v1/conflicts` API | Two sources disagreeing on a still-fresh attribute is surfaced as an open conflict, blocks proposals against that entity, and an operator resolution produces a hash-linked commit | Complete (in-memory only, not Postgres-backed; no CLI or MCP tool surface yet) |

Local fallback status (2026-09-08): five consecutive `reality rehearse --runs 5`
batches each reached `assurance_level=verified` for every loop; the deterministic
loop runs in single-digit milliseconds, far inside the three-to-four-minute demo
budget. `reality rehearse --fault provider_error` and `--fault
verification_divergence` confirm the loop stops at a protective terminal status
(`approved` with no proof, and `state_diverged`) rather than a false `verified`.

Outstanding before a live investor demo, all requiring real credentials or
infrastructure not in this repository:

- live Shopify/EasyPost authentication, scope, and behavior validation
  (`reality preflight`), and a full dress rehearsal against a real test order;
- a Railway deployment with a persistent volume for PostgreSQL.

---

## 16. Test strategy

### 16.1 Automated tests

- Unit tests for mapping, entity resolution, scoring, canonical serialization, hashes, policy rules, and transition validation.
- Contract tests for Shopify and EasyPost adapters using recorded/redacted fixtures.
- Integration tests with PostgreSQL and object storage.
- End-to-end tests for denied, rejected, stale, failed, divergent, and verified actions.
- Replay tests proving deterministic projection from the same observation set.
- Tenant-isolation tests for every API repository path.

### 16.2 Live-service tests

Before each demo:

1. Validate connector authentication and scopes.
2. Create or identify a fresh eligible Shopify test order.
3. Run bounded ingest and verify the expected World State.
4. Confirm the test action policy returns `approval_required`.
5. Confirm verification latency is below the demo timeout.
6. Reset the environment and preserve one fallback proof bundle.

---

## 17. Demo runbook

### 17.1 Preparation

- Create a fresh unfulfilled Shopify test order.
- Ensure no real payment/refund is involved.
- Associate a test shipment/tracking record in EasyPost.
- Run connector health checks and bounded ingest.
- Confirm the workspace is initially Observe-only, then explicitly enable demo proposal mode.
- Open the World State, Approval, and History/Proof screens in advance.

### 17.2 Three-to-four-minute script

| Time | Step | Message |
|---|---|---|
| 0:00–0:45 | Show World State | “The agent reads a compiled view of reality, including where each value came from and how fresh it is.” |
| 0:45–1:30 | Agent proposes cancellation | “The agent can express intent, but it cannot directly operate Shopify.” |
| 1:30–2:00 | Show policy decision | “Policy explains why human approval is required.” |
| 2:00–2:30 | Approve | “The gateway rechecks policy and state immediately before execution.” |
| 2:30–3:15 | Execute and verify | “The API response is not proof; the system independently reads Shopify again.” |
| 3:15–4:00 | Show diff and proof | “The final bundle connects intent, approval, external evidence, and the resulting state.” |

If time permits, finish with the denied observer proposal to demonstrate that policy is enforced rather than decorative.

---

## 18. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Shopify test state is unsuitable for cancellation | Core action fails | Preflight eligibility check and freshly seeded test order |
| External read-after-write is delayed | Demo stalls | Async polling, visible pending status, 30-second bound, prerecorded fallback |
| EasyPost does not represent a direct carrier source | Positioning confusion | Describe it accurately as a shipping API aggregator |
| Agent produces unexpected arguments | Unsafe or confusing proposal | Strict typed schema; reject unknown fields; fixed demo prompt |
| Retry duplicates side effects | Loss of trust | Semantic idempotency key, unique constraint, provider/state reconciliation |
| Projection changed after approval | Action based on stale reality | Expected state version and pre-execution revalidation |
| Hash chain is mistaken for signed proof | Overclaiming | Label it tamper-evident within the store, not independently notarized |
| Demo-mode same-person approval weakens separation | Governance concern | Record explicit exception in proof and explain production direction |
| Connector outage | Demo interruption | Preflight, cached observed state, fallback recording and proof bundle |

---

## 19. Definition of done

The Investor MVP is complete when all acceptance criteria pass and a live operator can repeatedly demonstrate:

```text
two real sources
  → permission-aware World State
  → typed agent proposal
  → explainable policy decision
  → explicit human approval
  → idempotent real write
  → independent external verification
  → semantic commit and proof at assurance level: verified
```

The team must resist expanding the slice until this loop is reliable. Connector breadth, autonomous execution, sophisticated conflict handling, richer policies, and production hardening begin only after the investor flow succeeds consistently.

---

## 20. Post-MVP expansion path

After the Demo Slice is proven, expand in this order:

1. Full conflict detection and resolution UX.
2. Durable HITL lifecycle with expiry, supersession, alternatives, and scoped approvals.
3. Additional verified actions.
4. A third source such as ERP, database, or CSV.
5. Stronger claim/provenance model and multi-source corroboration.
6. Policy-as-code and richer authorization.
7. Signed proof bundles and external integrity anchoring.
8. Production packaging, operational dashboards, and self-hosted deployment.
