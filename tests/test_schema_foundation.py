import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy.dialects import postgresql

from reality_layer.db.base import Base
from reality_layer.db.models import (
    ActionEvent,
    CommitLog,
    Connector,
    ObservationLog,
    PolicyVersion,
    StateProjection,
    Workspace,
)
from reality_layer.db.repositories import tenant_get_by_id, tenant_select

MVP_TABLES = {
    "workspace",
    "connector",
    "observation_log",
    "state_projection",
    "commit_log",
    "action_event",
    "policy_version",
}

#: Tables added after the investor MVP scope was frozen (see docs/mvp-design.md Phase 9+).
POST_MVP_TABLES = {
    "conflict",
}

APPEND_ONLY_TABLES = {
    "observation_log",
    "commit_log",
    "action_event",
    "policy_version",
}


def test_models_match_investor_mvp_table_set() -> None:
    assert set(Base.metadata.tables) == MVP_TABLES | POST_MVP_TABLES


def test_all_mvp_tables_are_tenant_scoped() -> None:
    for table in Base.metadata.tables.values():
        assert "tenant_id" in table.columns
        assert not table.columns["tenant_id"].nullable


def test_tenant_select_adds_tenant_filter() -> None:
    statement = tenant_select(StateProjection, "tenant_a")
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )

    assert "state_projection.tenant_id = 'tenant_a'" in str(compiled)


def test_tenant_get_by_id_adds_id_and_tenant_filters() -> None:
    statement = tenant_get_by_id(Workspace, "tenant_a", "workspace_id", "workspace_1")
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )

    sql = str(compiled)
    assert "workspace.tenant_id = 'tenant_a'" in sql
    assert "workspace.workspace_id = 'workspace_1'" in sql


def test_current_models_include_required_append_only_tables() -> None:
    append_only_models = (ObservationLog, CommitLog, ActionEvent, PolicyVersion)

    assert {model.__tablename__ for model in append_only_models} == APPEND_ONLY_TABLES


def test_mutable_configuration_tables_are_not_append_only() -> None:
    assert Workspace.__tablename__ not in APPEND_ONLY_TABLES
    assert Connector.__tablename__ not in APPEND_ONLY_TABLES


def test_append_only_triggers_are_in_alignment_migration() -> None:
    migration_path = Path("alembic/versions/20260907_0002_align_investor_mvp_schema.py")
    spec = importlib.util.spec_from_file_location("alignment_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert isinstance(migration, ModuleType)
    assert set(migration.APPEND_ONLY_TABLES) == APPEND_ONLY_TABLES
