import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from reality_layer.api.app import create_app
from reality_layer.config import Settings
from reality_layer.db.base import Base
from reality_layer.world_state import CompilerPersistenceService, Observation, WorldStateService


@pytest.fixture
def postgres_session_factory() -> Iterator[sessionmaker[Session]]:
    database_url = os.getenv("REALITY_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("REALITY_TEST_DATABASE_URL is required for PostgreSQL integration tests")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_persisted_generic_entity_api_round_trip(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    tenant_id = "postgres-tenant"
    observation = Observation(
        observation_id="obs_postgres_order",
        connector="shopify",
        object_type="order",
        object_id="postgres-order",
        observed_at=datetime.now(UTC),
        payload={"id": "postgres-order", "status": "open"},
    )
    world_state = WorldStateService()
    state = world_state.ingest(tenant_id, observation)
    commit = world_state.get_commit_for_state(tenant_id, state)

    with postgres_session_factory() as session:
        CompilerPersistenceService(session).persist(state, commit)
        session.commit()

    app = create_app(
        Settings(
            database_url=os.environ["REALITY_TEST_DATABASE_URL"],
            persistence_enabled=True,
        ),
        session_factory=postgres_session_factory,
    )

    with TestClient(app) as client:
        response = client.get(
            "/v1/entities/order/postgres-order",
            headers={"X-Reality-Tenant": tenant_id},
        )

    assert response.status_code == 200
    assert response.json()["entity_id"] == "order:postgres-order"
    assert response.json()["attributes"]["status"]["value"] == "open"
