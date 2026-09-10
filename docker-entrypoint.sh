#!/bin/sh
# Railway auto-detects the repo-root Dockerfile and does not apply railway.toml's
# [deploy] section, so `preDeployCommand = "alembic upgrade head"` never runs.
# Run migrations here instead, gated to the API service via RUN_MIGRATIONS=1 so
# the verifier (same image) does not race on DDL.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
fi

exec "$@"
