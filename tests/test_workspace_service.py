from reality_layer.db.models import ConnectorKind, WorkspaceMode
from reality_layer.workspaces import WorkspaceService


class FakeScalars:
    def __init__(self, value):
        self.value = value

    def first(self):
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value

    def all(self):
        return self.value


class FakeSession:
    def __init__(self):
        self.workspace = None
        self.connectors = []

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"].__name__
        if entity == "Workspace":
            return FakeScalars(self.workspace)
        return FakeScalars(self.connectors)

    def add(self, value):
        if value.__class__.__name__ == "Workspace":
            self.workspace = value
        else:
            self.connectors.append(value)

    def flush(self):
        return None


def test_initialize_creates_observe_only_workspace_and_connector_baseline() -> None:
    session = FakeSession()

    result = WorkspaceService(session).initialize("tenant-a", "workspace-a")

    assert result.workspace_id == "workspace-a"
    assert result.mode == WorkspaceMode.observe_only
    assert result.connector_ids == (
        "workspace-a_shopify",
        "workspace-a_easypost",
    )
    assert [connector.kind for connector in session.connectors] == [
        ConnectorKind.shopify,
        ConnectorKind.easypost,
    ]


def test_initialize_is_idempotent_for_existing_workspace() -> None:
    session = FakeSession()
    service = WorkspaceService(session)
    first = service.initialize("tenant-a", "workspace-a")
    second = service.initialize("tenant-a", "workspace-a")

    assert second == first
    assert len(session.connectors) == 2


def test_policy_defaults_to_observe_only_without_workspace() -> None:
    policy = WorkspaceService(FakeSession()).policy("tenant-a")

    assert policy.mode == WorkspaceMode.observe_only
    assert policy.value_limit is None


def test_policy_reads_persisted_mode_and_value_limit() -> None:
    session = FakeSession()
    WorkspaceService(session).initialize("tenant-a", "workspace-a")
    session.workspace.mode = WorkspaceMode.demo_proposal
    session.workspace.thresholds = {"write_value_limit": "100.5"}

    policy = WorkspaceService(session).policy("tenant-a")

    assert policy.mode == WorkspaceMode.demo_proposal
    assert policy.value_limit == 100.5


def test_record_connector_checks_persists_sanitized_capabilities() -> None:
    session = FakeSession()
    WorkspaceService(session).initialize("tenant-a", "workspace-a")

    WorkspaceService(session).record_connector_checks(
        "tenant-a",
        [
            {
                "connector": "shopify",
                "authenticated": True,
                "read_capability": True,
                "write_capability": True,
                "error": None,
            }
        ],
    )

    shopify = session.connectors[0]
    assert shopify.capabilities == {"read": True, "write": True}
    assert shopify.last_check == {"authenticated": True, "error": None}


def test_capability_requires_persisted_successful_connector_check() -> None:
    session = FakeSession()
    service = WorkspaceService(session)
    service.initialize("tenant-a", "workspace-a")

    assert not service.has_capability("tenant-a", ConnectorKind.shopify, "read")
    service.record_connector_checks(
        "tenant-a",
        [
            {
                "connector": "shopify",
                "authenticated": True,
                "read_capability": True,
                "write_capability": False,
                "error": None,
            }
        ],
    )

    assert service.has_capability("tenant-a", ConnectorKind.shopify, "read")
    assert not service.has_capability("tenant-a", ConnectorKind.shopify, "write")
