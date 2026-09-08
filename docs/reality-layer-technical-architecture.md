# Reality Layer — Technical Architecture

**Reality Compiler + Reality Git**

| Version | Date | Status |
| --- | --- | --- |
| 2.0 | September 6, 2026 | Living technical draft. Architecture decisions, schema definitions, and trust guarantees should be updated as implementation evidence and customer usage accumulate. |

> Source: `Reality_Layer_Technical_Architecture_v2.0_EN.docx`
> (https://docs.google.com/document/d/1a8h0BIUeuXAHgMZB9xU7qWW1hzoptMQ2/edit)
> This file is a faithful Markdown transcription of that document.

---

## 1. Purpose and Scope

This document defines the technical architecture of the Reality Layer for AI agents. The
layer provides a current, verified, permission-aware representation of the operational
world and a controlled path from an agent's intent to an externally verified result.

The first product version combines two core systems:

- **Reality Compiler** — transforms raw observations and agent activity into a structured,
  scored, queryable world state.
- **Reality Git** — maintains append-only history, diffs, provenance, decisions, actions,
  and proofs about how that world changed.

The architecture is designed for agent runtimes such as LangGraph, CrewAI, Claude Agent
SDK, MCP-compatible clients, and custom orchestrators. It does not depend on a specific
foundation model.

*HITL — Human in the loop.*

### Implementation status

This document describes the target architecture. The current repository implements the
core MVP control loop, but not every capability described below. Implemented areas include
observations, World State projections with provenance/confidence/freshness, typed actions,
policy evaluation, approval and precondition checks, idempotent test-adapter execution,
independent verification, hash-linked commits and action events, proof bundles, bounded
verification polling, and optional PostgreSQL persistence.

Conflict resolution, field-level redaction, ABAC, durable approval expiry and delegation,
MCP/SDK interfaces, complete workspace initialization, signed attestations, and dashboard
surfaces remain planned or partial. Treat architecture tables and examples as target
contracts unless a capability is listed as implemented in the MVP documentation.

## 2. Product Principles

| Principle | Architectural consequence |
| --- | --- |
| Observe before acting | The product contract requires every new workspace to start in Observe-only mode; the current demo runtime uses an explicit `demo_proposal` exception until durable workspace initialization is complete. |
| Facts are claims, not bare values | State carries provenance, freshness, confidence, and conflict status. |
| Intent is not execution | Agents propose actions; the Reality Layer authorizes, executes, and verifies them. |
| Auditability is a product feature | State transitions, decisions, overrides, failures, and proofs are versioned. |
| Human control is explicit | Risk- and policy-driven HITL gates are first-class workflow states. |
| Schemas evolve | Ontology and connector mappings are versioned independently from runtime state. |

## 3. High-Level Architecture

| Layer | Primary responsibilities | Examples |
| --- | --- | --- |
| Agent Layer | Reasoning, planning, task decomposition | LangGraph, CrewAI, custom agents |
| Agent-Facing Interface | Read state, query entities, propose actions, retrieve proofs and diffs | SDK, REST/gRPC API, MCP tools |
| Policy & Permission Engine | RBAC/ABAC, risk and cost rules, data redaction, HITL triggers | allow, deny, approval required |
| Action Gateway + Verifier | Preconditions, idempotent execution, observation, postconditions, attestation | cancel order, update address |
| Reality Store + Reality Git | Current state, snapshots, immutable commits, provenance graph | entity view, diff, audit trail |
| Reality Compiler | Normalize, resolve entities, detect conflicts, score confidence, detect changes | observations and activity events |
| Source & Connector Layer | Pull, push, webhooks, credential isolation, rate limits | ERP, CRM, carriers, databases |

## 4. Core Data Model

### 4.1 World State

World State is a tenant-scoped materialized view. It is optimized for agent reads and
operational decisions, while raw observations and commits remain the source of historical
truth.

```json
{
  "state_id": "uuid",
  "tenant_id": "org:acme/workspace:ops",
  "version": 142,
  "compiled_at": "2026-09-05T16:28:00Z",
  "schema_version": "order-to-cash/1.2.0",
  "entities": {
    "order:ORD-93821": {
      "type": "Order",
      "attributes": {"status": "shipped", "carrier": "UPS"},
      "confidence": 0.94,
      "freshness": "current",
      "provenance": [{"source": "ups_api", "observation_id": "obs_8f3a"}],
      "conflicts": [],
      "permissions": {"read": ["agent:ops"], "write": ["agent:ops"]}
    }
  },
  "relations": [
    {"from": "order:ORD-93821", "to": "shipment:SHP-4412", "type": "HAS_SHIPMENT", "confidence": 0.97}
  ]
}
```

### 4.2 Reality Git Commit

A commit records a meaningful world transition. It may originate from a new observation, a
verified action, conflict resolution, policy change, schema migration, or human override.

```json
{
  "commit_id": "cmt_9f2e1a",
  "parent_ids": ["cmt_8d4b2c"],
  "author": {"type": "agent", "id": "agent:ops-worker-07"},
  "cause": "verified_action",
  "message": "Order ORD-93821 changed from processing to shipped",
  "diff": {
    "entities_changed": ["order:ORD-93821"],
    "before": {"status": "processing"},
    "after": {"status": "shipped"}
  },
  "provenance": [{"source": "ups_api", "observation_id": "obs_8f3a"}],
  "action_ref": "act_3k9p2m",
  "proof": {"type": "attestation", "hash": "sha256:...", "signature": "..."}
}
```

### 4.3 Action Proposal and Execution Record

```json
{
  "action_id": "act_3k9p2m",
  "proposed_by": "agent:ops-worker-07",
  "action_type": "update_shipping_address",
  "target_entities": ["order:ORD-93821"],
  "parameters": {"new_address": {}},
  "preconditions": [{"check": "order.status == processing", "result": true}],
  "risk_score": 0.35,
  "cost_estimate": {"currency": "USD", "amount": 0},
  "requires_hitl": false,
  "status": "executed",
  "execution": {"postconditions_verified": true, "commit_id": "cmt_9f2e1a"},
  "proof": {}
}
```

## 5. Reality Compiler

The compiler is an incremental pipeline. Each stage is deterministic where possible,
observable, replayable, and independently versioned.

- **Ingest.** Connectors push or pull immutable observations. Each record includes tenant,
  source identity, source timestamp, receive timestamp, payload hash, raw payload
  reference, and connector version.
- **Normalize and map.** Connector-specific fields are mapped into the active canonical
  schema. The system supports typed core properties plus controlled extension attributes.
- **Resolve entities.** Deterministic keys are preferred; probabilistic matching is used
  only within configured thresholds. Ambiguous matches become review tasks rather than
  silent merges.
- **Detecting and resolving conflicts.** Competing claims are preserved. A resolution
  policy selects the effective value or escalates the case while retaining losing claims
  and evidence.
- **Score confidence and freshness.** Scores combine source reliability, observation age,
  independent corroboration, contradictions, extraction quality, and human verification.
- **Detect meaningful changes.** The compiler compares effective state, not raw payload
  noise. Only semantically relevant transitions create Reality Git commits.
- **Publish output.** Updated state, commits, conflict tasks, and subscription events are
  written atomically or through an outbox pattern.

## 6. Conflict Model and Resolution UX

Conflicts are normal operational objects, not exceptional errors. The system must explain
what disagrees, which value is currently effective, why it won, and what changes if a user
chooses another claim.

| Resolution strategy | When to use | Required audit data |
| --- | --- | --- |
| Source priority | A source is contractually authoritative | priority rule and policy version |
| Higher confidence | Evidence quality differs materially | component scores and explanation |
| Most recent valid claim | State changes rapidly and clocks are trusted | source time, receive time, clock quality |
| Keep multiple claims | The world can legitimately contain parallel states | claim scope and applicability |
| Human resolution | Impact or ambiguity exceeds threshold | reviewer, rationale, selected claim |
| Quarantine | Data appears corrupt, unsafe, or unmappable | quarantine reason and remediation status |

The dashboard should present a conflict queue, side-by-side evidence, confidence
decomposition, freshness, source health, downstream impact, and one-click resolution with
an optional expiry. Every resolution creates a commit.

## 7. Confidence, Freshness, and Trust

Confidence expresses support for a claim; freshness expresses whether the claim is recent
enough for its domain. They must not be collapsed into a single number. A highly reliable
but stale observation may still be unsafe for action.

```
effective_confidence = source_reliability x extraction_quality x corroboration
                       x conflict_penalty x human_verification_factor
```

- Decay functions are configured per entity type and attribute. Inventory quantity may
  decay in minutes; a tax identifier may remain valid for years.
- Independent corroboration must account for shared upstream sources to avoid
  double-counting copied data.
- Action policies can require minimum confidence, maximum age, a conflict-free claim, or
  explicit human confirmation.

## 8. Action Lifecycle: Proposal to Verification

1. The agent submits a typed proposal with target entities, parameters, reason, evidence
   references, and an idempotency key.
2. The interface loads a permission-filtered state snapshot and pins its version for
   evaluation.
3. The gateway validates schema, identity, permissions, preconditions, policy rules,
   estimated cost, and risk.
4. The decision is returned as `allowed`, `approval_required`, or `denied`, with
   machine-readable reasons.
5. If approval is required, the proposal becomes a durable workflow item with expiry and
   scope-limited approval.
6. Before execution, mutable preconditions are rechecked against the latest state to
   prevent time-of-check/time-of-use errors.
7. The connector executes with an idempotency key and records provider request/response
   references. *(Idempotency: running an operation multiple times yields the same final
   state as running it once; duplicate requests are safely ignored or handled.)*
8. The verifier observes the external system and evaluates postconditions. An API success
   response alone is not sufficient proof.
9. The compiler ingests the result, updates World State, and writes a linked Reality Git
   commit.
10. The caller receives status, resulting commit, evidence, and proof; partial and failed
    outcomes remain auditable.

## 9. Policy and Permission Engine

The engine combines identity, resource, attribute, action, environment, risk, cost,
confidence, and approval context. Evaluation must be deterministic, versioned,
explainable, and testable before deployment.

| Policy surface | MVP | Evolution |
| --- | --- | --- |
| Templates | Role templates for Operations, Support, and Finance | Vertical-specific packs and organizational inheritance |
| Authoring | Simple YAML/JSON rules | Visual Policy Builder and Python policy SDK |
| Evaluation | RBAC plus action/risk/cost conditions | ABAC, relationship rules, simulations, policy-as-code CI |
| Safety | Default deny for writes; Observe-only onboarding | Progressive trust levels and adaptive approval |
| Explainability | Decision reason and matched rule | Counterfactual explanation and impact preview |

Policy complexity must remain hidden from most users. Templates should cover common roles,
and advanced users should be able to extend them without forking the platform.

*ABAC: Attribute-Based Access Control — checks permissions based on traits/characteristics
instead of fixed job roles.*

## 10. Human-in-the-Loop

HITL is a durable state machine rather than a blocking API call. Approval requests include
proposed action, expected effect, relevant world-state diff, evidence, risk, cost,
confidence, policy reason, expiry, and available alternatives.

| State | Meaning |
| --- | --- |
| pending_approval | Waiting for a qualified reviewer |
| approved | Authorized within explicit scope and validity window |
| rejected | Reviewer denied execution with a reason |
| expired | Approval window elapsed |
| superseded | Underlying state or proposal changed |
| executing | Gateway accepted execution |
| verified / partial / failed | Final verification outcome |

## 11. Proof and Attestation Model

A proof demonstrates what the platform can verify, without overstating certainty. Proof
types can include provider receipts, webhook events, signed connector attestations,
read-after-write verification, independent-source confirmation, and hash-linked audit
records.

Proof bundles contain the action, policy decision, pinned pre-state, execution receipt,
post-state observations, verifier outcome, commit identifiers, and integrity hashes.

Cryptographic signing is optional for the MVP; canonical serialization and hash chaining
should be designed in from the start.

A proof states its assurance level and limitations. For example, "provider accepted
request" differs from "external state independently observed."

## 12. Reality Store and Reality Git

A pragmatic MVP uses PostgreSQL with relational columns for identity, tenancy, versioning,
and status; JSONB for flexible attributes and raw normalized payloads; and object storage
for large raw evidence. A graph database can be introduced later for workloads that
demonstrate a real traversal bottleneck.

| Store | Purpose |
| --- | --- |
| Observation log | Immutable source events and payload references |
| Claim store | Competing attribute-level claims, provenance, confidence, validity |
| Entity/relationship tables | Canonical identities and typed links |
| Current-state projection | Fast permission-filtered agent reads |
| Commit log | Append-only semantic diffs and parent links |
| Action/approval ledger | Proposal, decision, execution, verification, HITL |
| Outbox | Reliable publication to subscribers and downstream agents |

### 12.1 Branching Model

The operational world should have one authoritative mainline per workspace. Agent-specific
branches are useful only for simulation, planning, and proposed future state; they must
never be confused with observed reality. Merging a proposal means executing and verifying
actions, not merely applying a data diff.

## 13. Integration Surfaces

### 13.1 MCP

- `get_world_state` — return a permission-filtered snapshot with freshness and confidence.
- `query_entities` — search canonical entities, relationships, claims, and conflicts.
- `propose_action` — submit a typed intent for policy evaluation.
- `get_action_status` — retrieve durable execution and approval state.
- `get_proof` — retrieve a proof bundle and assurance level.
- `diff_since` — stream or query semantic changes since a commit or timestamp.

### 13.2 Direct SDK

```python
from reality_layer import RealityClient

client = RealityClient(api_key="...", agent_id="ops-worker-07")
state = client.get_world_state(entities=["order:ORD-93821"])
proposal = client.propose_action(
    type="cancel_order", target="order:ORD-93821",
    reason="customer_request", evidence=["ticket:TKT-122"])
proof = client.get_proof(proposal.action_id)
```

### 13.3 LangGraph Pattern

```python
def agent_node(state):
    world = reality.get_world_state(query=state["query"])
    proposal = reality.propose_action(...)
    if proposal.requires_hitl:
        return {"__interrupt__": proposal.action_id}
    return {"last_commit": proposal.commit_id}
```

## 14. Security, Isolation, and Audit

- **Authentication:** signed JWT or mTLS workload identity; no shared agent API keys in
  production.
- **Authorization:** organization → workspace → principal hierarchy, with entity-,
  attribute-, and action-level controls.
- **Credential isolation:** connector credentials are vault-managed and never exposed to
  agents.
- **Tenant isolation:** tenant identifiers are mandatory in storage keys, queues, caches,
  logs, and proofs; database row-level security is recommended.
- **Immutable audit:** commits and action records are append-only. Corrections create new
  records and preserve prior facts.
- **Privacy:** sensitive attributes can be encrypted, redacted, tokenized, or tombstoned
  while retaining non-personal integrity metadata.
- **Abuse controls:** rate limits, action budgets, blast-radius limits, anomaly detection,
  and emergency workspace freeze.

## 15. AGI and the Continuing Need for a Reality Layer

More capable general intelligence may improve planning, interpretation, and recovery, but
it does not remove the need for a Reality Layer. Intelligence cannot guarantee that a
source is current, that an identity is authorized, that an external system accepted a
change, or that the resulting state matches the intended outcome.

| Capability | AGI may improve | Reality Layer must still provide |
| --- | --- | --- |
| Understanding | Infer meaning from ambiguous data | Canonical claims, provenance, timestamps, schema versions |
| Planning | Select better multi-step strategies | Policy boundaries, budgets, permissions, approval gates |
| Execution | Adapt connector usage | Idempotency, credential isolation, preconditions |
| Validation | Form better hypotheses | Independent observation, postconditions, proofs |
| Coordination | Negotiate among agents | Shared event semantics and authoritative history |

As agents become more autonomous, the value of a model-independent control and evidence
plane increases. The Reality Layer is infrastructure for trustworthy autonomy, not a
substitute for intelligence.

## 16. Inter-Agent Communication and the Agent Activity Compiler

Operational coordination should not rely primarily on human-language transcripts. Natural
language remains useful for explanation and negotiation, but durable coordination should
use typed events that preserve intent, evidence, state references, and outcomes.

### 16.1 Agent Activity Event

```json
{
  "event_id": "evt_71f2",
  "event_type": "action.proposed",
  "actor": "agent:support-04",
  "target": "order:ORD-93821",
  "intent": "cancel_order",
  "inputs": {"reason": "customer_request"},
  "evidence": ["ticket:TKT-122", "commit:cmt_8d4b2c"],
  "state_version": 142,
  "timestamp": "2026-09-05T16:27:50Z",
  "status": "claimed"
}
```

### 16.2 Event Semantics

| Event class | Examples | Meaning |
| --- | --- | --- |
| Observation | observation.received, claim.created | An agent or connector reports evidence |
| Decision | decision.proposed, decision.approved | A choice and its policy/approval context |
| Action | action.proposed, action.started | An intended or initiated external effect |
| Result | action.verified, action.partial, action.failed | Observed execution outcome |
| Coordination | task.claimed, task.delegated, task.released | Ownership and handoff among agents |

### 16.3 Agent Activity Compiler

The Agent Activity Compiler consumes structured events, tool calls, approvals, connector
receipts, and selected explanatory traces. It reconstructs what an agent attempted, links
activity to affected entities and commits, detects duplicate or contradictory actions, and
updates the operational picture.

- Reasoning should be stored as a concise rationale plus evidence references, not as
  unrestricted private chain-of-thought.
- Tool activity becomes a claim until independently verified; a successful tool response
  does not automatically become world truth.
- The compiler enables cross-agent deduplication, causal timelines, accountability, and
  replay without requiring agents to share one model or prompt format.

## 17. Layered Reality Schema and Ontology

An ontology makes the platform more robust and easier to maintain only when it is layered,
versioned, and bounded. Building a bespoke ontology for every workflow would create
excessive modeling overhead and brittle customer deployments.

| Layer | Ownership | Examples |
| --- | --- | --- |
| Core Reality Schema | Platform | Entity, Claim, Observation, Action, Agent, Proof, Conflict, Commit |
| Domain Pack | Platform/community | Order-to-Cash: Order, Shipment, Inventory, Invoice, Customer |
| Organization Extensions | Customer | Internal status, business unit, custom relationship, approval class |
| Connector Mappings | Connector owner | Shopify order_status → Order.status |
| Runtime State | Compiler | Resolved entities, effective claims, conflicts, confidence, provenance |

### 17.1 What the Ontology Enables

- Stronger validation of entity types, attributes, relationships, action targets, and
  pre/postconditions.
- Reusable policy templates that refer to semantic types instead of connector-specific
  field names.
- Clear conflict explanations because the system understands whether values are
  equivalent, mutually exclusive, or scoped differently.
- More stable APIs for agents and dashboards even when underlying systems change.
- Safer migrations through explicit schema versions, compatibility rules, and mapping
  tests.

### 17.2 Schema Versioning and Migration

- Use semantic versions for domain packs and immutable schema releases.
- Store `schema_version` on observations, claims, commits, action proposals, and proofs.
- Require migration plans for breaking changes and support dual-read/dual-write windows
  where necessary.
- Replay historical observations through a new compiler version without rewriting the
  original observation log.
- Provide sample payload tests, mapping coverage, policy compatibility checks, and preview
  diffs before activation.

### 17.3 MVP Boundary

Start with a compact Order-to-Cash ontology of approximately 10–20 entity types and 30–50
relationships. Define only concepts required by the first connectors, actions, policies,
conflicts, and dashboards. Add concepts through real use cases rather than attempting to
model the entire business domain upfront.

## 18. User Installation, Onboarding, and Daily Use

The primary experience should move users from visibility to controlled autonomy.
Installation must produce useful observations before asking the user to author complex
policies or enable writes.

### 18.1 Quick Start

```bash
pip install reality-layer
reality init
reality connect shopify
reality connect ups
reality observe
reality serve --mcp
```

After `reality init`, the workspace is always Observe-only. Connectors run least-privilege
read checks, discover supported schema mappings, backfill a bounded history, and produce a
first World State plus a data-quality report.

### 18.2 Trust Progression

| Stage | User experience | Allowed system behavior |
| --- | --- | --- |
| Observe | See current state, conflicts, provenance, and agent activity | Read and analyze only |
| Propose | Review recommended actions and simulated impact | Create proposals; no external writes |
| Approve | Human approves selected action classes | Execute within explicit approval scope |
| Autonomous | Low-risk actions run under budgets and policies | Execute, verify, commit, alert on exceptions |

### 18.3 Dashboard

- **Reality:** entities, confidence, freshness, provenance, and unresolved conflicts.
- **Agents:** what each agent proposed or did, why, evidence used, and resulting state
  changes.
- **Approvals:** risk-ranked queue, impact preview, policy reason, and expiry.
- **History:** readable commit timeline and clear before/after diff between commits.
- **Policies:** templates first, then a visual builder; advanced users can use YAML or
  Python.
- **Health:** connector status, stale sources, mapping coverage, compiler lag, and
  verification failures.

### 18.4 Managed and Self-Hosted

Managed and self-hosted deployments should expose the same CLI, SDK, API, schema packs,
and policy model. Migration should primarily change endpoint, identity provider, and
deployment configuration. Export/import tooling must preserve observations, commits, schema
versions, policies, and proof references.

## 19. Recommended MVP Vertical

Order-to-Cash / Supply Operations remains the recommended first vertical because it offers
clear entities, costly mistakes, multiple independent sources, meaningful write actions,
and measurable operational outcomes.

| MVP capability | Initial scope |
| --- | --- |
| Connectors | Two or three: Shopify, one carrier, and a database or ERP |
| Compiler | Ingest, mapping, deterministic resolution, basic conflicts, confidence, change detection |
| Reality Git | Append-only commits, entity diff, provenance links, snapshot reference |
| Policy/HITL | Role templates, risk/cost thresholds, durable approval flow |
| Actions | Five to seven high-value operations with idempotency and verification |
| Interfaces | Python SDK, REST API, basic MCP server |
| Dashboard | Reality, conflicts, agents, approvals, history, source health |
| Ontology | Compact Order-to-Cash domain pack with connector mapping tests |

## 20. Key Technical Decisions

| Decision area | Recommendation for MVP | Revisit trigger |
| --- | --- | --- |
| State storage | PostgreSQL + JSONB + object storage | Measured graph traversal bottleneck |
| History | Custom append-only commit model over event/claim tables | Need for cross-region notarization or external verification |
| Compilation | Event-driven incremental compile plus scheduled reconciliation | Source cannot provide deltas or sustained lag |
| Branches | Single authoritative mainline; simulation branches only | Concrete multi-workspace merge use case |
| Long-running actions | Async state machine with polling/webhook verifier | Provider-specific orchestration dominates |
| Schema | Layered versioned ontology with controlled extensions | Repeated customer friction or incompatible verticals |
| Cryptography | Canonical hashes and chain links; optional signatures | Regulated customer or cross-party proof requirement |

## 21. Engineering Next Steps

1. Finalize the Order-to-Cash core entities, relationships, actions, and claim semantics.
2. Implement immutable observation ingestion and the claim store in PostgreSQL.
3. Define the Reality Git commit envelope, canonical diff format, and hash strategy.
4. Build the minimal compiler path: ingest → map → resolve → score → project → commit.
5. Implement permission-filtered query APIs and the six core MCP tools.
6. Connect one real read source and one real write action with read-after-write
   verification.
7. Add durable HITL workflow, expiry, revalidation, and audit events.
8. Ship Observe-only onboarding, conflict queue, action rationale/evidence, and commit
   diff views.
9. Add domain-pack versioning, mapping contract tests, and migration preview.
10. Measure prevented failures, verification coverage, conflict resolution time, audit
    completeness, and end-to-end latency.

## 22. Success Metrics

| Metric | Definition |
| --- | --- |
| Prevented unsafe action rate | Proposals denied or escalated because state, permission, policy, or confidence was insufficient |
| Verification coverage | Executed actions with a conclusive postcondition result and evidence bundle |
| World-state freshness | Percent of action-relevant claims within configured freshness SLO |
| Conflict resolution time | Median time from conflict detection to effective resolution |
| Audit completeness | Percent of state transitions linked to source evidence, actor, cause, and schema version |
| Decision latency | P50/P95 time for reads, proposal evaluation, approval, execution, and verification |
| User trust progression | Workspaces that safely move from Observe to Propose, Approve, and bounded autonomy |
