from reality_layer.db.models import ConnectorKind, WorkspaceMode
from reality_layer.workspaces import WorkspaceService


class FakeScalars:
    def __init__(self, value):
        self.value = value

    def first(self):
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
