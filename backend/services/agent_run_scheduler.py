from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from backend.agent_core.reliability import AgentExecutionPolicy
from backend.models.agent_run import AgentRunRecord, AgentRunStatus
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord
from backend.services.agent_run_store import (
    AgentRunStore,
    AgentRunStoreConflictError,
    AgentRunStoreNotFoundError,
)


@dataclass(frozen=True, slots=True)
class AgentProfileBudget:
    policy: AgentExecutionPolicy
    max_parallel_tools: int


PROFILE_BUDGETS = {
    AgentRuntimeProfile.INTERACTIVE: AgentProfileBudget(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=45,
            tool_timeout_seconds=20,
            max_safe_retries=2,
            max_plan_steps=4,
            max_tool_calls=4,
        ),
        max_parallel_tools=1,
    ),
    AgentRuntimeProfile.LONG_TASK: AgentProfileBudget(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=1800,
            tool_timeout_seconds=120,
            max_safe_retries=2,
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

    def retry(self, run_id: str) -> AgentRunRecord:
        current = self.store.get_run(run_id)
        if current is None:
            raise AgentRunStoreNotFoundError(f"run not found: {run_id}")
        if current.status is not AgentRunStatus.FAILED:
            raise AgentRunStoreConflictError(
                f"run {run_id} cannot retry from {current.status.value}"
            )
        retry_run = AgentRunRecord(
            task_id=current.task_id,
            run_id=f"run-{uuid4().hex}",
            trace_id=f"trace-{uuid4().hex}",
            runtime_profile=current.runtime_profile,
            status=AgentRunStatus.QUEUED,
        )
        return self.store.create_run(
            retry_run,
            request_payload=self.store.get_run_request(run_id) or {},
        )


__all__ = ["PROFILE_BUDGETS", "AgentProfileBudget", "AgentRunScheduler"]
