from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(pattern=r"^obs_[A-Za-z0-9_-]+$")
    connector: str = Field(min_length=1, max_length=64)
    object_type: str = Field(pattern=r"^(order|shipment)$")
    object_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    payload: dict[str, Any]


class StateAttribute(BaseModel):
    value: Any
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime
    freshness: str
    source_observation_ids: list[str]


class OrderState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    entity_id: str
    entity_type: str
    state_version: int
    attributes: dict[str, StateAttribute]
    commit_id: str


class CommitRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_id: str
    tenant_id: str
    parent_commit_id: str | None = None
    entity_type: str
    entity_id: str
    cause: str
    observation_ids: list[str]
    before: dict[str, Any]
    after: dict[str, Any]
    semantic_diff: dict[str, Any]
    assurance_level: str
    previous_hash: str | None = None
    hash: str
