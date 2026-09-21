from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, computed_field

from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import (
    TERMINAL_TASK_STATUSES,
    TaskExecutionState,
    TaskModel,
    utc_now,
)
from backend.models.agent_tools import AgentToolEffect


class AgentRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }
)


class InvalidRunTransitionError(ValueError):
    pass


_ALLOWED_RUN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: frozenset(
        {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED}
    ),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.WAITING,
            AgentRunStatus.PAUSE_REQUESTED,
            AgentRunStatus.RECOVERING,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.WAITING: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.PAUSE_REQUESTED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.PAUSE_REQUESTED: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.PAUSED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.PAUSED: frozenset(
        {AgentRunStatus.RECOVERING, AgentRunStatus.CANCELLED}
    ),
    AgentRunStatus.RECOVERING: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.PAUSED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
}


class AgentRunRecord(TaskModel):
    task_id: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=256)
    trace_id: str = Field(min_length=1, max_length=256)
    runtime_profile: AgentRuntimeProfile
    status: AgentRunStatus = AgentRunStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentStepRecord(TaskExecutionState):
    """Runtime-bound view of the existing orchestration task state."""

    run_id: str = Field(min_length=1, max_length=256)

    @computed_field
    @property
    def step_id(self) -> str:
        return self.task_id


class AgentToolCallStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AgentToolCallRecord(TaskModel):
    tool_call_id: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=256)
    step_id: str = Field(min_length=1, max_length=256)
    tool_name: str = Field(min_length=1, max_length=256)
    effect: AgentToolEffect
    arguments_hash: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    status: AgentToolCallStatus = AgentToolCallStatus.PENDING
    attempt: int = Field(default=1, ge=1)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    timeout_ms: int = Field(gt=0)
    error_type: str = Field(default="", max_length=256)
    error_message: str = Field(default="", max_length=4000)
    result_ref: str = Field(default="", max_length=512)


class AgentWorkerLeaseRecord(TaskModel):
    run_id: str = Field(min_length=1, max_length=256)
    lease_owner: str = Field(min_length=1, max_length=256)
    lease_expires_at: datetime
    heartbeat_at: datetime


def transition_run(run: AgentRunRecord, target: AgentRunStatus) -> AgentRunRecord:
    if run.status == target:
        return run.model_copy(deep=True)
    allowed = _ALLOWED_RUN_TRANSITIONS.get(run.status, frozenset())
    if target not in allowed:
        raise InvalidRunTransitionError(
            f"invalid run transition: {run.status.value} -> {target.value}"
        )

    now = utc_now()
    updates: dict[str, object] = {"status": target, "updated_at": now}
    if target is AgentRunStatus.RUNNING and run.started_at is None:
        updates["started_at"] = now
    if target in TERMINAL_RUN_STATUSES:
        updates["finished_at"] = now
    return run.model_copy(update=updates, deep=True)


def is_terminal_run(run: AgentRunRecord) -> bool:
    return run.status in TERMINAL_RUN_STATUSES


def is_terminal_step(step: AgentStepRecord) -> bool:
    return step.status in TERMINAL_TASK_STATUSES


__all__ = [
    "TERMINAL_RUN_STATUSES",
    "AgentRunRecord",
    "AgentRunStatus",
    "AgentStepRecord",
    "AgentToolCallRecord",
    "AgentToolCallStatus",
    "AgentWorkerLeaseRecord",
    "InvalidRunTransitionError",
    "is_terminal_run",
    "is_terminal_step",
    "transition_run",
]
