# Railway builds this repo from the Dockerfile (Nixpacks is no longer a
# selectable builder, and Railway auto-detects a repo-root Dockerfile). The
# Reality Layer needs its own package installed - not just its dependencies - so
# the `reality` / `alembic` console scripts are on PATH and `reality_layer` is
# importable by `alembic/env.py`. See docs/deployment-railway.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY . .
RUN pip install --upgrade pip && pip install .

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8080

# The entrypoint runs `alembic upgrade head` first when RUN_MIGRATIONS=1
# (set on the API service only; the verifier shares this image).
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["reality", "serve", "--host", "0.0.0.0", "--port", "8080"]
