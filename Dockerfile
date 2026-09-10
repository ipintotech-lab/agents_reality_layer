# Railway now builds with Railpack or a Dockerfile (Nixpacks is no longer a
# selectable builder). The Reality Layer needs its own package installed — not
# just its dependencies — so the `reality` / `alembic` console scripts are on
# PATH and `reality_layer` is importable by `alembic/env.py`. A Dockerfile gives
# us that deterministically; see docs/deployment-railway.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY . .
RUN pip install --upgrade pip && pip install .

EXPOSE 8080

# Overridden per-service by railway.toml's [deploy].startCommand (API) or the
# service's custom start command (verifier: `reality verify`).
CMD ["reality", "serve", "--host", "0.0.0.0", "--port", "8080"]
