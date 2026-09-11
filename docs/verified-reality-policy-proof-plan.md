# Verified Reality + Policy/Proof Architecture Plan

## Goal

Move from a central-executor model to a verified-reality model in which Reality Layer is responsible for:

- maintaining a trusted, queryable World State;
- evaluating policy and approvals deterministically;
- issuing a scoped, signed Capability Token when a decision allows an action;
- verifying external execution and producing a proof bundle.

Execution may remain in the customer or agent environment, while the Reality Layer retains custody of the policy decision, evidence, and final proof.

## Guiding principles

- Backward compatible as much as possible.
- Progressive rollout with a legacy feature flag.
- Secure by default: short-lived, scoped, signed tokens.
- Audit first: every decision, token, external report, and verification result is recorded in Reality Git.
- Clear separation: policy decision != execution.

## Architectural shift

Before:

```text
Agent → propose → Reality Layer (policy + execute + verify) → External Systems
```

After:

```text
Agent → propose → Reality Layer (World State + Policy + Decision/Token)
                ↓
         Agent / Customer Executor → External Systems
                ↓
         Reality Layer ← verification / proof report
```

The Reality Layer continues to own the authoritative policy decision and proof trail, but it does not need to hold customer credentials or directly perform every external action in the new operating model.

## New components

### Capability Token Issuer

Creates a signed token containing:

- token_id
- action_id
- action_type
- target_entities
- constraints
- principal
- issued_at
- expires_at
- state_version
- workspace_id
- policy_version
- signature

### Token schema and validation

Defines canonical JSON serialization, required claims, audience, expiry handling, and signature verification rules. The token is a proof of delegated permission, not a substitute for verification.

### Decision Envelope

A unified response model for action outcomes:

```json
{
  "status": "allowed",
  "reason": "Policy approved",
  "decision": {
    "action_id": "act_123",
    "status": "approved",
    "policy_version": "policy:v1.4",
    "required_role": "operations"
  },
  "token": {
    "token_id": "tok_456",
    "action_id": "act_123",
    "expires_at": "2026-09-11T12:40:00Z",
    "state_version": 142,
    "signature": "..."
  },
  "proof_refs": ["proof:abc"]
}
```

When approval is required, the response may instead return `approval_required` with a pending decision and a token once approved.

### Execution mode config

Add a workspace-level execution setting:

- `reality_executes`
- `customer_executes`
- `hybrid`

This should live alongside the existing workspace mode configuration and default to the current behavior during the migration.

### Verification ingress

The API accepts external execution reports and evidence from the agent or customer system, then validates the result by reading the target state again and producing a proof bundle.

## Changes to existing components

- `propose_action` should return a Decision Envelope and optional Capability Token instead of only a runtime execution result.
- The Action Gateway becomes optional and only active in `reality_executes` mode.
- The policy engine remains deterministic and continues to emit explicit reasons and matched rules.
- The Action Ledger supports states such as:
  - `token_issued`
  - `executed_externally`
  - `verification_pending`
  - `verified`
  - `verification_failed`
  - `revoked`
- MCP/REST interfaces add `get_decision`, `report_execution`, and optionally `validate_token`.
- The dashboard should show decision status, token issuance, external execution status, and proof state.

## Phased rollout

### Phase 0 — Preparation

- Define the Capability Token schema.
- Define canonical serialization and signing rules.
- Add `execution_mode` to workspace configuration.
- Write an ADR explaining the new trust model and migration strategy.

### Phase 1 — Decision + Token

Goal: `propose_action` returns a decision and token without executing.

1. Keep deterministic policy evaluation.
2. If allowed or approved, issue a Capability Token.
3. Store the token and decision in the action ledger and Reality Git.
4. Add `get_decision` and `get_token` interfaces.
5. Preserve the legacy path behind `REALITY_EXECUTION_MODE=legacy`.

### Phase 2 — Customer execution path

Goal: agent/customer executes and reports back.

1. Add `POST /v1/actions/{id}/report_execution`.
2. Accept provider references, evidence, and execution status.
3. Run read-after-write verification.
4. Update ledger status to `executed_externally` and `verification_pending`.
5. Transition to `verified` or `verification_failed` based on independent evidence.

### Phase 3 — Hybrid + HITL

- Support HITL gating before token issuance.
- Enforce expiry and scope constraints.
- Allow `hybrid` mode with delegated execution and explicit proof capture.

### Phase 4 — Hardening and DX

- Add customer-side library support for token validation.
- Provide examples for MCP, LangGraph, and Claude Agent SDK flows.
- Update demo docs and runbooks.
- Capture operational metrics: time-to-token, token utilization ratio, verification success rate.

## Recommended MVP priority order

1. `propose_action` returns Decision + Capability Token.
2. Token and decision are recorded in the ledger + Reality Git.
3. `report_execution` and basic verification are supported.
4. Feature flag switches between legacy and new behavior.
5. Demo and docs are updated to the new flow.

Only after this should the product add client-side validation libraries and more advanced hybrid execution modes.

## Definition of done

The updated architecture is complete when this flow works end-to-end:

1. Agent reads World State.
2. Proposes action.
3. Receives `allowed` or `approval_required` plus Capability Token.
4. Agent/customer executes externally if allowed.
5. Reports back with provider refs and evidence.
6. Reality Layer verifyies the resulting state.
7. Proof + commit are generated and persisted.

The flow must work in both Observe-only and Proposal modes and remain compatible with the current local fallback rehearsal and live-preflight paths.
