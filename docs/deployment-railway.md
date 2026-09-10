# Deploying the Reality Layer to Railway

This is the operator procedure for standing up a persistent, connector-backed
environment for the investor demo. The local fallback path (`reality rehearse`,
`reality demo`) needs none of this — see [`demo-runbook.md`](demo-runbook.md).

Railway is the target because the design (§10.1 of [`mvp-design.md`](mvp-design.md))
calls for a managed Postgres and a small always-on API + worker. Any equivalent
host works; the shapes below are what matters.

## 0. Prerequisites

- A Railway account and a new empty project.
- The `railway` CLI installed locally (`npm i -g @railway/cli`).
- Shopify development store credentials and an EasyPost **test** API key.

> **`railway login` is interactive (browser OAuth) and cannot be completed from an
> automated session.** Run every `railway ...` command in this document yourself
> from a normal terminal.

## 1. Topology

One Railway **project** with three components:

| Component | Type | Purpose |
| --- | --- | --- |
| `Postgres` | Railway Postgres plugin | World State, commits, action events, conflicts. Has its own managed volume. |
| `reality-api` | service from this repo | FastAPI app (`reality serve`) + dashboard at `/`. |
| `reality-verifier` | service from this repo | Read-after-write verifier worker (`reality verify`). |

Both services deploy the **same repo and commit**; they differ only in start
command and in whether they need a volume.

## 2. Provision Postgres

```bash
railway add --plugin postgresql
```

Railway now exposes `DATABASE_URL` (and `PG*` vars) on a reference you can attach
to other services. The plugin's storage is a managed volume — no extra
configuration needed for the database itself.

## 3. Deploy `reality-api`

Create the service pointed at this repo (GitHub integration or `railway up` from a
clone). The repo root ships a `Dockerfile` (Railway no longer offers Nixpacks as a
builder) that runs `pip install .` so the `reality` / `alembic` entry points and
the `reality_layer` package used by `alembic/env.py` are importable.

- Railway auto-detects the `Dockerfile` and builds from it. It does **not** apply
  `railway.toml`'s `[deploy]` section on a `railway up` deploy, so:
  - the container start command is the Dockerfile `CMD`
    (`reality serve --host 0.0.0.0 --port 8080`);
  - **migrations run from the image entrypoint**, not `preDeployCommand`:
    `docker-entrypoint.sh` runs `alembic upgrade head` when `RUN_MIGRATIONS=1`
    (set that variable on `reality-api` only — see 3.1 — so the verifier, which
    shares the image, does not race on DDL);
  - there is no Railway healthcheck; the container is routable as soon as it
    starts listening.
- Bind `0.0.0.0` (the `CMD` does). An IPv6-only bind (`::`) makes Railway's edge
  proxy return `502 Application failed to respond`.

### 3.1 Environment variables

Set these on the `reality-api` service:

| Variable | Value | Notes |
| --- | --- | --- |
| `REALITY_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Reference variable. The plain `postgresql://` scheme is auto-rewritten to `postgresql+psycopg://` by `Settings` (psycopg v3 is the pinned driver). |
| `REALITY_PERSISTENCE_ENABLED` | `true` | Required — turns on the Postgres-backed code paths. |
| `RUN_MIGRATIONS` | `1` | `reality-api` only. The image entrypoint runs `alembic upgrade head` on boot. Do **not** set this on the verifier. |
| `PORT` | `8080` | Matches the Dockerfile `CMD` and the service domain's target port. |
| `REALITY_ENVIRONMENT` | `railway` | |
| `REALITY_WORKSPACE_MODE` | `observe_only` | Product contract: a fresh workspace must start observe-only. The operator flips it to `demo_proposal` at demo time. |
| `REALITY_OBJECT_STORAGE_ROOT` | `/data/raw_payloads` | Must be inside the mounted volume — see 3.2. |
| `REALITY_SHOPIFY_DOMAIN` | `your-store.myshopify.com` | |
| `REALITY_SHOPIFY_ACCESS_TOKEN` | *(secret)* | Sealed variable; never commit. |
| `REALITY_EASYPOST_API_KEY` | *(test-mode secret)* | |
| `REALITY_WRITE_VALUE_LIMIT` | `500.0` | Optional guard rail. |

### 3.2 Attach a persistent volume for raw payloads

`LocalObjectStore` writes immutable raw connector payloads to
`REALITY_OBJECT_STORAGE_ROOT` on the container filesystem. **Railway container
storage is ephemeral** — without a volume every redeploy or restart silently drops
the referenced payloads and observation `raw_payload` refs dangle.

```bash
railway volume add --mount-path /data --service reality-api
```

Then keep `REALITY_OBJECT_STORAGE_ROOT=/data/raw_payloads` (as in 3.1).

> The database is safe without this step (managed plugin volume); the object store
> is not.

### 3.3 First deploy

```bash
railway up --service reality-api
```

Watch the deploy logs for `[entrypoint] alembic upgrade head` running to
`20260910_0003` (or later) and `Uvicorn running on http://0.0.0.0:8080`.

### 3.4 Public domain

```bash
railway domain --service reality-api --port 8080
```

If you generated the domain *before* the first successful deploy, its target
port can be left unset and every request returns `404` with
`x-railway-fallback: true`. Fix it in the dashboard (**Settings → Networking**,
set the target port to `8080`) or just delete the domain and generate a new one
now that the service is live.

## 4. Deploy `reality-verifier`

Add a second service from the same repo. Override its start command:

```
reality verify
```

Give it the **same** environment variables as `reality-api` **except** it does not
serve HTTP and does not need the volume (it only reads/writes Postgres). Disable
its healthcheck (no port). It shares `REALITY_DATABASE_URL` with the API.

Set its start command in the Railway service settings (railway.toml's
`startCommand` only covers the API): **Settings → Deploy → Custom Start Command →
`reality verify`**. The CLI cannot set a per-service start command.

Do **not** put `alembic upgrade head` on this service — migrations belong to the
API's `preDeployCommand` only, to avoid two services racing on the same DDL.

## 5. Post-deploy smoke test

From your terminal (`$API` = the `reality-api` public URL):

```bash
curl -s "$API/healthz"                       # {"status":"ok","version":"..."}
curl -s "$API/v1/preflight" | jq .ready      # false until connectors are wired
curl -s -H "X-Reality-Tenant: demo" "$API/v1/workspace" | jq .mode   # "observe_only"
```

Initialize the demo tenant and validate connectors against the deployed env:

```bash
railway run --service reality-api reality init --tenant demo
railway run --service reality-api reality connect shopify easypost --tenant demo
railway run --service reality-api reality preflight --tenant demo
```

`preflight` must report `"ready": true` before you attempt the live control-loop
demo. From here, follow [`demo-runbook.md`](demo-runbook.md) §2–§6, substituting
`railway run --service reality-api reality ...` for the local `reality ...`
invocations, or drive the same steps over REST against `$API`.

## 6. Reset between live rehearsals

- Do **not** reuse a cancelled Shopify order. Seed a fresh unfulfilled development
  order and matching EasyPost test shipment.
- To wipe World State between rehearsals without redeploying:
  `railway run --service reality-api alembic downgrade base && railway run --service reality-api alembic upgrade head`
  (this also clears the `conflict`, `commit_log`, and `action_event` tables).
- The attached volume persists raw payloads across this reset; that is harmless
  (they are content-addressed and immutable) but you may clear `/data/raw_payloads`
  if you want a pristine object store.

## 7. What this does not cover

- TLS / custom domain (Railway provides a `*.up.railway.app` URL with TLS by
  default — sufficient for the demo).
- Horizontal scaling of the API (single instance is fine for the demo; the
  Postgres-backed conflict/state code is already multi-worker safe if you scale).
- Secrets rotation and least-privilege Shopify scopes — use a dev store.
