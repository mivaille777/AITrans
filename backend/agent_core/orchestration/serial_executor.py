from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from backend.agent_core.multi_agent.context import KnowledgeInjector, SharedAgentContext
from backend.agent_core.orchestration.reducer import reduce_task_results
from backend.models.agent_tasks import (
    ScopeContext,
    TaskResult,
    TaskRole,
    TaskSpec,
    TaskStatus,
    ValidatedTaskPlan,
)


@dataclass(frozen=True, slots=True)
class SpecialistExecution:
    result: TaskResult
    output: Any = None
    direct_delivery: bool = False


class SpecialistExecutor(Protocol):
    def execute(
        self,
        *,
        task: TaskSpec,
        scope: ScopeContext,
        dependency_results: Mapping[str, TaskResult],
        memory_snapshot: Mapping[str, Any],
    ) -> SpecialistExecution: ...


@dataclass(frozen=True, slots=True)
class SerialExecution:
    results: tuple[TaskResult, ...]
    outputs: dict[str, Any]
    direct_output: Any = None
    direct_delivery: bool = False


class LegacySpecialistExecutor:
    """Temporary compatibility adapter until MA04/MA05 expert subgraphs replace it."""

    _LEGACY_NAMES: ClassVar[dict[TaskRole, str]] = {
        TaskRole.DOCUMENT: "reading",
        TaskRole.RESEARCH: "research",
    }

    def __init__(self, registry: Any, *, evidence_service: Any | None = None) -> None:
        self._registry = registry
        self._injector = KnowledgeInjector(evidence_service=evidence_service)

    def execute(
        self,
        *,
        task: TaskSpec,
        scope: ScopeContext,
        dependency_results: Mapping[str, TaskResult],
        memory_snapshot: Mapping[str, Any],
    ) -> SpecialistExecution:
        legacy_name = self._LEGACY_NAMES.get(task.role)
        agent = self._registry.get(legacy_name) if legacy_name else None
        if agent is None:
            return SpecialistExecution(
                result=TaskResult(
                    task_id=task.task_id,
                    attempt_id=f"{task.task_id}:1",
                    status=TaskStatus.BLOCKED,
                    error_code="specialist_not_implemented",
                    unmet_requirements=[f"{task.role.value}_specialist"],
                )
            )
        context = SharedAgentContext(
            query=task.objective,
            runtime={"scope_context": scope},
            memory=dict(memory_snapshot),
            intermediate_results=dict(dependency_results),
        )
        if self._injector.evidence_service is not None:
            self._injector.inject(task.objective, context)
        legacy_result = agent.execute(task.objective, context)
        output = getattr(legacy_result, "output", legacy_result)
        return SpecialistExecution(
            result=TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:1",
                status=TaskStatus.PARTIAL,
                warnings=["legacy_specialist_preview_without_typed_artifact"],
            ),
            output=output,
        )


class SerialTaskGraphExecutor:
    def __init__(self, executors: Mapping[TaskRole, SpecialistExecutor]) -> None:
        self._executors = dict(executors)

    def execute(
        self,
        *,
        plan: ValidatedTaskPlan,
        scope: ScopeContext,
        memory_snapshot: Mapping[str, Any] | None = None,
        run_id: str = "",
        collector: Any | None = None,
        control: Any | None = None,
    ) -> SerialExecution:
        del run_id, collector, control
        pending = plan.task_map()
        results: list[TaskResult] = []
        by_id: dict[str, TaskResult] = {}
        outputs: dict[str, Any] = {}
        direct_output: Any = None
        direct_delivery = False
        non_leaf_task_ids = {
            dependency for task in plan.tasks for dependency in task.depends_on
        }

        while pending:
            ready = [
                task
                for task in pending.values()
                if all(dependency in by_id for dependency in task.depends_on)
            ]
            if not ready:
                raise RuntimeError("validated task plan has no executable frontier")
            for task in sorted(ready, key=lambda item: item.task_id):
                dependency_results = {
                    dependency: by_id[dependency] for dependency in task.depends_on
                }
                failed_dependencies = [
                    item
                    for item in dependency_results.values()
                    if item.status
                    not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL}
                ]
                if failed_dependencies:
                    execution = SpecialistExecution(
                        result=TaskResult(
                            task_id=task.task_id,
                            attempt_id=f"{task.task_id}:1",
                            status=TaskStatus.BLOCKED,
                            error_code="dependency_unavailable",
                            unmet_requirements=sorted(
                                item.task_id for item in failed_dependencies
                            ),
                        )
                    )
                else:
                    executor = self._executors.get(task.role)
                    if executor is None:
                        execution = SpecialistExecution(
                            result=TaskResult(
                                task_id=task.task_id,
                                attempt_id=f"{task.task_id}:1",
                                status=TaskStatus.BLOCKED,
                                error_code="specialist_not_registered",
                            )
                        )
                    else:
                        try:
                            execution = executor.execute(
                                task=task,
                                scope=scope,
                                dependency_results=dependency_results,
                                memory_snapshot=dict(memory_snapshot or {}),
                            )
                        except Exception as exc:  # noqa: BLE001 - task failure is isolated
                            execution = SpecialistExecution(
                                result=TaskResult(
                                    task_id=task.task_id,
                                    attempt_id=f"{task.task_id}:1",
                                    status=TaskStatus.FAILED,
                                    error_code=type(exc).__name__,
                                )
                            )
                if execution.result.task_id != task.task_id:
                    raise ValueError("specialist returned a result for a different task")
                by_id[task.task_id] = execution.result
                results = reduce_task_results(results, [execution.result])
                if execution.output is not None:
                    outputs[task.task_id] = execution.output
                if execution.direct_delivery and task.task_id not in non_leaf_task_ids:
                    direct_output = execution.output
                    direct_delivery = True
                pending.pop(task.task_id)

        return SerialExecution(
            results=tuple(results),
            outputs=outputs,
            direct_output=direct_output,
            direct_delivery=direct_delivery,
        )


__all__ = [
    "LegacySpecialistExecutor",
    "SerialExecution",
    "SerialTaskGraphExecutor",
    "SpecialistExecution",
    "SpecialistExecutor",
]
