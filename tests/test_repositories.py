from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from reality_layer.db.models import StateProjection
from reality_layer.db.repositories import (
    ActionEventRepository,
    ObservationRepository,
    StateProjectionRepository,
    tenant_get_by_id,
)


def test_state_projection_primary_key_is_tenant_scoped() -> None:
    primary_key = StateProjection.__table__.primary_key

    assert [column.name for column in primary_key.columns] == ["tenant_id", "entity_id"]


def test_repository_queries_preserve_tenant_filter() -> None:
    statement = tenant_get_by_id(StateProjection, "tenant_a", "entity_id", "order:1")
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )

    assert "state_projection.tenant_id = 'tenant_a'" in str(compiled)


def test_repository_types_expose_persistence_operations() -> None:
    assert ObservationRepository.__init__.__annotations__["session"] is Session
    assert StateProjectionRepository.__init__.__annotations__["session"] is Session
    assert ActionEventRepository.__init__.__annotations__["session"] is Session
