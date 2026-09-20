from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_tasks import (
    ScopeContext,
    TaskResult,
    TaskRole,
    TaskSpec,
    TaskStatus,
    ValidatedTaskPlan,
)


def scope() -> ScopeContext:
    return ScopeContext.issue(
        profile_id="profile-scheduler",
        workspace_id="workspace-scheduler",
        scope_revision="revision-1",
        allowed_document_ids=["paper-a", "paper-b"],
    )


def plan(
    task_ids: tuple[str, ...] = ("a", "b"),
    *,
    dependencies: Mapping[str, list[str]] | None = None,
) -> ValidatedTaskPlan:
    active_scope = scope()
    dependency_map = dict(dependencies or {})
    return ValidatedTaskPlan(
        plan_id="plan-scheduler",
        scope_ref=active_scope.scope_ref,
        tasks=[
            TaskSpec(
                task_id=task_id,
                role=TaskRole.DOCUMENT,
                objective=f"Analyze {task_id}",
                depends_on=dependency_map.get(task_id, []),
                required=True,
                expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
                scope_ref=active_scope.scope_ref,
                allowed_tools=["search_knowledge_base"],
            )
            for task_id in task_ids
        ],
    )


def success(task_id: str, *, attempt: int = 1) -> SpecialistExecution:
    return SpecialistExecution(
        result=TaskResult(
            task_id=task_id,
            attempt_id=f"{task_id}:{attempt}",
            attempt_ordinal=attempt,
            status=TaskStatus.SUCCEEDED,
        ),
        output={"task_id": task_id},
    )


class FunctionExecutor:
    def __init__(self, function: Callable[[TaskSpec], SpecialistExecution]) -> None:
        self.function = function
        self.calls: list[str] = []

    def execute(
        self,
        *,
        task: TaskSpec,
        scope: ScopeContext,
        dependency_results: Mapping[str, TaskResult],
        memory_snapshot: Mapping[str, Any],
    ) -> SpecialistExecution:
        del scope, dependency_results, memory_snapshot
        self.calls.append(task.task_id)
        return self.function(task)
