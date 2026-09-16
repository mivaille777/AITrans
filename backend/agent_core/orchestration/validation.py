from __future__ import annotations

from backend.agent_core.orchestration.roles import RoleRegistry
from backend.models.agent_tasks import ScopeContext, TaskSpec, ValidatedTaskPlan


class TaskPlanValidationError(ValueError):
    pass


def validate_task_plan(
    plan: ValidatedTaskPlan,
    *,
    scope: ScopeContext,
    role_registry: RoleRegistry | None = None,
) -> ValidatedTaskPlan:
    registry = role_registry or RoleRegistry()
    if plan.scope_ref != scope.scope_ref:
        raise TaskPlanValidationError(
            "plan scope_ref does not match the authoritative server ScopeContext"
        )

    tasks = plan.task_map()
    for task in plan.tasks:
        try:
            registry.require_tools(task.role, task.allowed_tools)
        except (KeyError, ValueError) as exc:
            raise TaskPlanValidationError(str(exc)) from exc
        _validate_inputs(task, tasks)
    return plan


def _validate_inputs(
    task: TaskSpec,
    tasks: dict[str, TaskSpec],
) -> None:
    dependencies = set(task.depends_on)
    for ref in task.input_refs:
        producer_id = ref.producer_task_id.strip()
        if not producer_id:
            continue
        producer = tasks.get(producer_id)
        if producer is None:
            raise TaskPlanValidationError(
                f"task {task.task_id} references unknown producer {producer_id}"
            )
        if producer_id not in dependencies:
            raise TaskPlanValidationError(
                f"task {task.task_id} input from {producer_id} must declare it as a dependency"
            )
        if producer.expected_output_kind != ref.kind:
            raise TaskPlanValidationError(
                f"task {task.task_id} expects {ref.kind.value} from {producer_id}, "
                f"but producer declares {producer.expected_output_kind.value}"
            )


__all__ = ["TaskPlanValidationError", "validate_task_plan"]
