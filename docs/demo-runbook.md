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

The `--summary` output includes `elapsed_seconds`; five runs should complete well
inside the three-to-four-minute demo window.

### Failure injection

Prove the loop fails safe rather than claiming an unverified write:

```bash
reality rehearse --runs 3 --fault provider_error           # provider rejects the write
reality rehearse --runs 3 --fault verification_divergence  # source still reports the order open
```

Each fault run emits a scenario summary with `all_protected`, per-run
`terminal_statuses`, and `slowest_step_ms` latency. The command exits non-zero
unless every run reaches its protective terminal status (`approved` with no proof
for `provider_error`; `state_diverged` for `verification_divergence`).

## 1a. Scripted agent walkthrough

Run the scripted agent demo, which drives the happy path, the policy-control
denial, and the proposal-only path entirely through the public MCP and REST
contracts:

```bash
reality demo --order demo-1001
```

The transcript attributes each step to an actor (`agent` / `operator` /
`system`) and a channel (`mcp` / `rest`). The run exits non-zero unless the
happy path reaches `assurance_level=verified`. Add `--proof` to print, or
`--output artifacts/demo-proof.json` to save, the happy-path proof bundle.

The same three screens are visible in the dashboard at `/` while the loop runs
(`reality serve`).

## 2. Live preflight

The live path needs a persistent, connector-backed environment. To stand one up on
Railway (managed Postgres, API + verifier services, persistent volume for raw
payloads), follow [`deployment-railway.md`](deployment-railway.md) first, then run
the steps below with `railway run --service reality-api reality ...` in place of the
bare `reality ...` calls. Running locally against a local Postgres works too.

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

When the matching EasyPost tracker is known, validate both sides together:

```bash
REALITY_PERSISTENCE_ENABLED=true reality preflight \
  --tenant demo --order-id 123 --shipment-id shp_123
```

The result must include eligible `demo_order` and `demo_shipment` checks.
The same sanitized check is available to REST clients at
`GET /v1/preflight?order_id=123&shipment_id=shp_123`.

Confirm that Shopify read and write capabilities are enabled and that EasyPost read
access succeeds. Stop the demo if either connector is unauthenticated or the
designated Shopify order is not an eligible, unfulfilled test order.

The workspace starts in `observe_only`; agent write proposals are denied
(`deny.workspace.observe_only`) until an operator enables proposal mode:

```bash
REALITY_PERSISTENCE_ENABLED=true reality workspace --tenant demo                       # show current mode
REALITY_PERSISTENCE_ENABLED=true reality workspace --tenant demo --mode demo_proposal  # enable proposals
```

The same transition is available over the API as `POST /v1/workspace/mode`
(`X-Reality-Role` must be `operations`, `admin`, or `system`), and the current
mode is shown in the dashboard header and by `GET /v1/workspace`.

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

## 7. Live demo go/no-go checklist

Run through this immediately before presenting. Every row must be **yes** or the
demo falls back to the recorded local proof bundle (§1).

| # | Check | How | Pass condition |
| --- | --- | --- | --- |
| 1 | Environment is up | `curl $API/healthz` | `{"status":"ok",...}` |
| 2 | Migrations current | deploy logs / `alembic current` | head revision (`20260910_0003` or later) |
| 3 | Verifier running | `reality-verifier` service logs | periodic sweep lines, no crash loop |
| 4 | Connectors authenticated | `reality preflight --tenant demo` | `"ready": true` |
| 5 | Target order eligible | `reality preflight --tenant demo --order-id <id>` | `demo_order` check eligible, status `open`, unfulfilled |
| 6 | Linked shipment present | `... --shipment-id <shp>` | `demo_shipment` check present |
| 7 | Workspace observe-only | `reality workspace --tenant demo` | mode `observe_only` |
| 8 | Bounded ingest clean | `reality observe shopify --tenant demo --limit 10 --persist` then `GET /v1/entities/order/<id>` | order visible with provenance, confidence, freshness, commit id |
| 9 | Policy denies unauthorized write | agent `cancel_order` as observer role | `denied`, rule `deny.observer.write` |
| 10 | Verification latency in budget | timed `reality verify --once` after a test proposal | `verified` within `REALITY_VERIFIER_TIMEOUT_SECONDS` (30s) |
| 11 | Fallback proof on hand | `artifacts/rehearsal-proof.json` exists and ends `assurance_level=verified` | present |

If checks 1–3 fail, the deployment is broken — fix it or present entirely from the
fallback bundle. If 4–6 fail, the connector/order state is wrong — reseed. If
10 fails, raise `REALITY_VERIFIER_TIMEOUT_SECONDS` or fall back.

After the demo, immediately return the workspace to `observe_only` and do not reuse
the cancelled order (§6).
