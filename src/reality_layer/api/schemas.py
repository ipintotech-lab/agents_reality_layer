from typing import Any

from pydantic import BaseModel, ConfigDict

from reality_layer.db.models import WorkspaceMode


class WorkspaceModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: WorkspaceMode


class ConflictResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_value: Any
    reason: str
