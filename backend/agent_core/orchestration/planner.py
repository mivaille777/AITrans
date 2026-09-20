from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.agent_core.orchestration.roles import RoleRegistry
from backend.agent_core.orchestration.validation import validate_task_plan
from backend.models.agent_artifacts import ArtifactKind
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


_OUTPUT_BY_ROLE = {
    TaskRole.DOCUMENT: ArtifactKind.DOCUMENT_ANALYSIS,
    TaskRole.RESEARCH: ArtifactKind.COMPARISON,
    TaskRole.WRITER: ArtifactKind.MANUSCRIPT_SECTION,
    TaskRole.CURATOR: ArtifactKind.KNOWLEDGE_DRAFT,
}

_OUTLINE_TERMS = ("outline", "大纲")
_REVISION_TERMS = ("revise", "revision", "修改", "修订", "只改")


def _expected_output(role: TaskRole, objective: str) -> ArtifactKind:
    if role is not TaskRole.WRITER:
        return _OUTPUT_BY_ROLE[role]
    lowered = str(objective).casefold()
    if any(term in lowered for term in _OUTLINE_TERMS):
        return ArtifactKind.OUTLINE
    if any(term in lowered for term in _REVISION_TERMS):
        return ArtifactKind.REVISION
    return ArtifactKind.MANUSCRIPT_SECTION

_TOOLS_BY_ROLE = {
    TaskRole.DOCUMENT: ["inspect_reading_context", "search_knowledge_base"],
    TaskRole.RESEARCH: ["analyze_cross_document_research", "search_knowledge_base"],
    TaskRole.WRITER: ["get_research_note", "polish_selection"],
    TaskRole.CURATOR: ["get_research_note", "search_knowledge_base"],
}


class ValidatedSupervisorPlanner:
    def __init__(
        self,
        *,
        role_registry: RoleRegistry | None = None,
        provider: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._roles = role_registry or RoleRegistry()
        self._provider = provider

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
            or route.primary_role is None
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
                    return validate_task_plan(plan, scope=scope, role_registry=self._roles)
                except (TypeError, ValueError, KeyError) as exc:
                    error = str(exc)
            raise SupervisorPlanningError(
                f"supervisor plan remained invalid after one repair: {error}"
            )
        return validate_task_plan(
            self._deterministic_plan(
                route=route,
                objective=objective,
                scope=scope,
                plan_revision=plan_revision,
            ),
            scope=scope,
            role_registry=self._roles,
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
        return TaskSpec(
            task_id=task_id,
            role=role,
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
            expected_output_kind=_expected_output(role, objective),
            acceptance_criteria=["scoped_sources_only", "typed_artifact_or_explicit_partial"],
            scope_ref=scope.scope_ref,
            allowed_tools=list(_TOOLS_BY_ROLE[role]),
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
