from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.agent_core.orchestration.agent_registry import (
    AgentRegistry,
    AgentSpec,
    build_default_agent_registry,
)
from backend.agent_core.orchestration.roles import RoleRegistry
from backend.agent_core.orchestration.validation import validate_task_plan
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import (
    ScopeContext,
    TaskInputRef,
    TaskRole,
    TaskSpec,
    ValidatedTaskPlan,
)


class SupervisorPlanningError(ValueError):
    pass


class ValidatedSupervisorPlanner:
    def __init__(
        self,
        *,
        role_registry: RoleRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
        provider: Callable[..., dict[str, Any]] | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        if role_registry is not None and agent_registry is not None:
            raise ValueError("Provide role_registry or agent_registry, not both")
        self._agents = (
            agent_registry
            or (role_registry.agent_registry if role_registry is not None else None)
            or build_default_agent_registry()
        )
        self._roles = role_registry or RoleRegistry(agent_registry=self._agents)
        self._provider = provider
        self._tool_registry = tool_registry

    def available_agents(self) -> tuple[AgentSpec, ...]:
        """Expose the registry's planning and execution capabilities."""

        return self._agents.list_agents()

    @property
    def agent_registry(self) -> AgentRegistry:
        return self._agents

    def resolve_agent(self, agent_id: str) -> AgentSpec:
        return self._agents.get(agent_id)

    def plan(
        self,
        *,
        route: OrchestrationRoute,
        objective: str,
        scope: ScopeContext,
        plan_revision: int = 1,
    ) -> ValidatedTaskPlan | None:
        if (
            route.lane is OrchestrationLane.FAST
            or route.missing_information
        ):
            return None
        if self._provider is not None:
            error = ""
            for attempt in range(2):
                try:
                    payload = self._provider(
                        objective=objective,
                        route=route.model_dump(mode="json"),
                        scope_ref=scope.scope_ref,
                        plan_revision=plan_revision,
                        repair_error=error,
                        attempt=attempt + 1,
                    )
                    plan = ValidatedTaskPlan.model_validate(payload)
                    return validate_task_plan(
                        plan,
                        scope=scope,
                        role_registry=self._roles,
                        tool_registry=self._tool_registry,
                    )
                except (TypeError, ValueError, KeyError) as exc:
                    error = str(exc)
            raise SupervisorPlanningError(
                f"supervisor plan remained invalid after one repair: {error}"
            )
        if route.primary_role is None:
            return None
        return validate_task_plan(
            self._deterministic_plan(
                route=route,
                objective=objective,
                scope=scope,
                plan_revision=plan_revision,
            ),
            scope=scope,
            role_registry=self._roles,
            tool_registry=self._tool_registry,
        )

    def validate(
        self,
        plan: ValidatedTaskPlan | None,
        *,
        scope: ScopeContext,
        require_graphs: bool = False,
    ) -> ValidatedTaskPlan | None:
        """Validate a proposed plan against the authoritative current scope."""

        if plan is None:
            return None
        return validate_task_plan(
            plan,
            scope=scope,
            role_registry=self._roles,
            agent_registry=self._agents,
            tool_registry=self._tool_registry,
            require_graphs=require_graphs,
        )

    def _task(
        self,
        *,
        task_id: str,
        role: TaskRole,
        objective: str,
        scope: ScopeContext,
        revision: int,
        depends_on: list[TaskSpec] | None = None,
        required: bool = True,
        target_source_ids: list[str] | None = None,
    ) -> TaskSpec:
        dependencies = list(depends_on or [])
        agent = self._agents.for_role(role)
        return TaskSpec(
            task_id=task_id,
            role=role,
            agent_id=agent.agent_id,
            objective=objective,
            depends_on=[item.task_id for item in dependencies],
            required=required,
            input_refs=[
                TaskInputRef(
                    artifact_id=f"artifact:{item.task_id}",
                    version=1,
                    kind=item.expected_output_kind,
                    producer_task_id=item.task_id,
                )
                for item in dependencies
            ],
            expected_output_kind=agent.output_for(objective),
            acceptance_criteria=["scoped_sources_only", "typed_artifact_or_explicit_partial"],
            scope_ref=scope.scope_ref,
            allowed_tools=list(agent.default_tools),
            plan_revision=revision,
            target_source_ids=list(target_source_ids or []),
        )

    def _deterministic_plan(
        self,
        *,
        route: OrchestrationRoute,
        objective: str,
        scope: ScopeContext,
        plan_revision: int,
    ) -> ValidatedTaskPlan:
        role = route.primary_role or TaskRole.DOCUMENT
        if route.lane is OrchestrationLane.SINGLE:
            tasks = [
                self._task(
                    task_id=f"{role.value}-1",
                    role=role,
                    objective=objective,
                    scope=scope,
                    revision=plan_revision,
                    target_source_ids=(
                        list(scope.allowed_document_ids)
                        if role is TaskRole.DOCUMENT
                        else []
                    ),
                )
            ]
        else:
            document_ids = list(scope.allowed_document_ids)
            document_tasks = [
                self._task(
                    task_id=f"document-{index}",
                    role=TaskRole.DOCUMENT,
                    objective=f"Analyze document {document_id} for: {objective}",
                    scope=scope,
                    revision=plan_revision,
                    target_source_ids=[document_id],
                )
                for index, document_id in enumerate(document_ids, start=1)
            ]
            tasks = list(document_tasks)
            dependencies: list[TaskSpec] = list(document_tasks)
            if role in {TaskRole.RESEARCH, TaskRole.WRITER} and len(document_tasks) > 1:
                research = self._task(
                    task_id="research-1",
                    role=TaskRole.RESEARCH,
                    objective=objective,
                    scope=scope,
                    revision=plan_revision,
                    depends_on=document_tasks,
                )
                tasks.append(research)
                dependencies = [research]
            if role is not TaskRole.RESEARCH or not any(
                task.role is TaskRole.RESEARCH for task in tasks
            ):
                tasks.append(
                    self._task(
                        task_id=f"{role.value}-1",
                        role=role,
                        objective=objective,
                        scope=scope,
                        revision=plan_revision,
                        depends_on=dependencies,
                    )
                )
            if not tasks:
                tasks.append(
                    self._task(
                        task_id=f"{role.value}-1",
                        role=role,
                        objective=objective,
                        scope=scope,
                        revision=plan_revision,
                    )
                )
        return ValidatedTaskPlan(
            plan_id=f"plan-{plan_revision}",
            plan_revision=plan_revision,
            scope_ref=scope.scope_ref,
            tasks=tasks,
        )


__all__ = ["SupervisorPlanningError", "ValidatedSupervisorPlanner"]
