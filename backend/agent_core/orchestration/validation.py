from __future__ import annotations

from backend.agent_core.orchestration.agent_registry import AgentRegistry
from backend.agent_core.orchestration.roles import RoleRegistry
from backend.models.agent_tasks import (
    ScopeContext,
    TaskRole,
    TaskSpec,
    ValidatedTaskPlan,
)


class TaskPlanValidationError(ValueError):
    pass


def validate_task_plan(
    plan: ValidatedTaskPlan,
    *,
    scope: ScopeContext,
    role_registry: RoleRegistry | None = None,
    agent_registry: AgentRegistry | None = None,
    tool_registry: object | None = None,
    require_graphs: bool = False,
) -> ValidatedTaskPlan:
    registry = (
        agent_registry
        or (role_registry.agent_registry if role_registry is not None else None)
        or RoleRegistry().agent_registry
    )
    if plan.scope_ref != scope.scope_ref:
        raise TaskPlanValidationError(
            "plan scope_ref does not match the authoritative server ScopeContext"
        )

    tasks = plan.task_map()
    for task in plan.tasks:
        try:
            agent = registry.get(task.agent_id)
            registry.require_tools(task.agent_id, task.allowed_tools)
        except (KeyError, ValueError) as exc:
            raise TaskPlanValidationError(str(exc)) from exc
        if task.role is not None and task.agent_id != task.role.value:
            raise TaskPlanValidationError(
                f"task {task.task_id} role and agent_id do not match"
            )
        if task.expected_output_kind not in agent.output_kinds:
            raise TaskPlanValidationError(
                f"task {task.task_id} expects unsupported output kind "
                f"{task.expected_output_kind.value} from Agent {agent.agent_id}"
            )
        unsupported_inputs = sorted(
            ref.kind.value
            for ref in task.input_refs
            if ref.kind not in agent.accepted_input_kinds
        )
        if unsupported_inputs:
            raise TaskPlanValidationError(
                f"task {task.task_id} uses unsupported input kinds: {unsupported_inputs}"
            )
        if require_graphs and not callable(agent.graph_factory):
            raise TaskPlanValidationError(
                f"Agent {agent.agent_id} has no registered graph factory"
            )
        if tool_registry is not None:
            get_tool = getattr(tool_registry, "get_tool", None)
            if not callable(get_tool):
                raise TypeError("tool_registry must expose get_tool")
            unknown_tools = [name for name in task.allowed_tools if get_tool(name) is None]
            if unknown_tools:
                raise TaskPlanValidationError(
                    f"task {task.task_id} references tools not configured on the server: "
                    f"{sorted(unknown_tools)}"
                )
        unknown_sources = set(task.target_source_ids) - (
            set(scope.allowed_document_ids)
            | set(scope.allowed_note_ids)
            | set(scope.allowed_item_ids)
        )
        if unknown_sources:
            raise TaskPlanValidationError(
                f"task {task.task_id} targets sources outside scope: {sorted(unknown_sources)}"
            )
        if task.role is TaskRole.DOCUMENT:
            non_documents = set(task.target_source_ids) - set(
                scope.allowed_document_ids
            )
            if non_documents:
                raise TaskPlanValidationError(
                    f"document task {task.task_id} targets non-document sources: "
                    f"{sorted(non_documents)}"
                )
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
