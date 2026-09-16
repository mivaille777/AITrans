from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from backend.models.agent_tasks import TaskRole


class OrchestrationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class OrchestrationLane(str, Enum):
    FAST = "fast"
    SINGLE = "single"
    WORKFLOW = "workflow"


class OrchestrationRoute(OrchestrationContract):
    lane: OrchestrationLane
    primary_role: TaskRole | None = None
    reason_code: str = Field(min_length=1, max_length=128)
    user_visible_reason: str = Field(default="", max_length=1000)
    missing_information: list[str] = Field(default_factory=list, max_length=16)


__all__ = ["OrchestrationLane", "OrchestrationRoute"]
