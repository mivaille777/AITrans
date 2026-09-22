from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from backend.agent_core.reliability import AgentExecutionPolicy
from backend.models.agent_run import AgentRunRecord, AgentRunStatus
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord
from backend.services.agent_run_store import AgentRunStore


@dataclass(frozen=True, slots=True)
class AgentProfileBudget:
    policy: AgentExecutionPolicy
    max_parallel_tools: int


PROFILE_BUDGETS = {
    AgentRuntimeProfile.INTERACTIVE: AgentProfileBudget(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=45,
            tool_timeout_seconds=20,
            max_plan_steps=4,
            max_tool_calls=4,
        ),
        max_parallel_tools=1,
    ),
    AgentRuntimeProfile.LONG_TASK: AgentProfileBudget(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=1800,
            tool_timeout_seconds=120,
            max_plan_steps=20,
            max_tool_calls=40,
        ),
        max_parallel_tools=4,
    ),
}


class AgentRunScheduler:
    """Durably enqueue a task and its first run without executing in the caller."""

    def __init__(self, store: AgentRunStore) -> None:
        self.store = store

    def enqueue(
        self,
        *,
        goal: str,
        runtime_profile: AgentRuntimeProfile = AgentRuntimeProfile.INTERACTIVE,
        workspace_id: str = "",
        task_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        request_payload: dict[str, object] | None = None,
    ) -> AgentRunRecord:
        task = AgentTaskRecord(
            task_id=task_id or f"task-{uuid4().hex}",
            goal=goal,
            workspace_id=workspace_id,
        )
        run = AgentRunRecord(
            task_id=task.task_id,
            run_id=run_id or f"run-{uuid4().hex}",
            trace_id=trace_id or f"trace-{uuid4().hex}",
            runtime_profile=runtime_profile,
            status=AgentRunStatus.QUEUED,
        )
        self.store.create_task_and_run(task, run, request_payload=request_payload)
        return run

    def cancel(self, run_id: str) -> AgentRunRecord:
        return self.store.cancel_run(run_id)

    def pause(self, run_id: str) -> AgentRunRecord:
        return self.store.pause_run(run_id)

    def resume(self, run_id: str) -> AgentRunRecord:
        return self.store.resume_run(run_id)


__all__ = ["PROFILE_BUDGETS", "AgentProfileBudget", "AgentRunScheduler"]
