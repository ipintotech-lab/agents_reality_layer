# Investor MVP Demo Runbook

This runbook covers the repeatable local fallback path and the live connector-backed
path. The live path must use a dedicated Shopify development order and EasyPost test
data only.

## 1. Local fallback rehearsal

Install the project with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run five isolated control loops and save a machine-readable summary:

```bash
reality rehearse --runs 5 --summary --output artifacts/rehearsal-summary.json
```

The summary is ready for fallback use when:

- `all_verified` is `true`;
- `verified_runs` equals `total_runs`;
- every proof has `assurance_level` equal to `verified`.

Capture a static proof bundle when needed:

```bash
reality rehearse --output artifacts/rehearsal-proof.json
```

## 2. Live preflight

Set connector credentials through the runtime secret mechanism. Do not place them in
proof files, shell history, or committed `.env` files.

Initialize the tenant workspace:

```bash
REALITY_PERSISTENCE_ENABLED=true reality init --tenant demo
```

Validate both connectors without printing credentials:

```bash
REALITY_PERSISTENCE_ENABLED=true reality connect shopify easypost --tenant demo
```

Run the single live-demo gate:

```bash
REALITY_PERSISTENCE_ENABLED=true reality preflight --tenant demo
```

The preflight must report `"ready": true`. It requires Shopify authentication,
read, and write capabilities plus EasyPost authentication and read capability.
When a target order has been selected, include `--order-id <shopify-order-id>` to
validate that exact order is open and unfulfilled:

```bash
REALITY_PERSISTENCE_ENABLED=true reality preflight --tenant demo --order-id 123
```

Confirm that Shopify read and write capabilities are enabled and that EasyPost read
access succeeds. Stop the demo if either connector is unauthenticated or the
designated Shopify order is not an eligible, unfulfilled test order.

## 3. Observe and inspect

Run bounded reads from both sources:

```bash
REALITY_PERSISTENCE_ENABLED=true reality observe shopify --tenant demo --limit 10 --persist
REALITY_PERSISTENCE_ENABLED=true reality observe easypost --tenant demo --limit 10 --persist
```

Confirm that the target order and shipment are visible with provenance, confidence,
freshness, and producing commit IDs.

## 4. Controlled action flow

The agent reads World State and submits a typed `cancel_order` proposal. The proposal
must identify the dedicated test order, expected state version, expected `open` status,
and a unique semantic idempotency key.

The operator then:

1. Confirms the policy response is `approval_required`.
2. Reviews the target, expected state, evidence, and provider side effects.
3. Approves using the Operations role.
4. Confirms execution returns `provider_accepted`, not `verified`.
5. Runs the verifier worker or waits for the bounded worker sweep:

```bash
reality verify --once
```

6. Retrieves the action proof and confirms `assurance_level` is `verified`.
7. Checks the semantic diff and verification commit.

## 5. Stop conditions and fallback

Stop execution immediately if:

- the expected state version is stale;
- the target is fulfilled, closed, or already cancelled;
- the connector capability check fails;
- verification diverges or times out;
- a proof contains credentials or unexpected sensitive fields.

Use the static fallback proof only as a demonstration artifact and label it as a
previously captured local rehearsal. It is not evidence that the live provider was
called during the current demo.

## 6. Reset

For local rehearsals, each run creates isolated in-memory services and deterministic
test data; rerun the five-run command to reset and validate the fallback path.

For live rehearsals, do not reuse a cancelled order. Create or select a fresh,
unfulfilled Shopify development order and a matching EasyPost test shipment before
repeating the flow.
