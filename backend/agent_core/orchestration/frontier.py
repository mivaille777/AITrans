from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from backend.agent_core.orchestration.reducer import (
    reduce_artifact_refs,
    reduce_evidence_refs,
)
from backend.agent_core.orchestration.task_state import failure_status_for_required_task
from backend.models.agent_artifacts import ArtifactRef, EvidenceRef
from backend.models.agent_tasks import (
    TERMINAL_TASK_STATUSES,
    TaskResult,
    TaskSpec,
    TaskStatus,
    ValidatedTaskPlan,
)

_SUCCESS_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.PARTIAL})
_DISPATCHABLE_STATUSES = frozenset({TaskStatus.PENDING, TaskStatus.READY})


class FrontierStateConflictError(ValueError):
    pass


def _status(value: TaskStatus | str) -> TaskStatus:
    return value if isinstance(value, TaskStatus) else TaskStatus(str(value))


def _result_map(
    results: Mapping[str, TaskResult | Mapping[str, Any]]
    | Iterable[TaskResult | Mapping[str, Any]],
) -> dict[str, TaskResult]:
    if isinstance(results, Mapping):
        pairs = results.items()
    else:
        pairs = ((None, item) for item in results)

    normalized: dict[str, TaskResult] = {}
    for key, raw in pairs:
        result = raw if isinstance(raw, TaskResult) else TaskResult.model_validate(raw)
        task_id = str(key).strip() if key is not None else result.task_id
        if task_id != result.task_id:
            raise FrontierStateConflictError(
                f"result key does not match task_id: {task_id} != {result.task_id}"
            )
        previous = normalized.get(task_id)
        if previous is not None and previous.content_hash != result.content_hash:
            raise FrontierStateConflictError(
                f"conflicting result supplied for task_id={task_id}"
            )
        normalized[task_id] = result
    return normalized


@dataclass(frozen=True, slots=True)
class DependencyProjection:
    """Typed view of only a task's declared upstream result references."""

    results: Mapping[str, TaskResult]
    artifact_refs: tuple[ArtifactRef, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    failed_task_ids: tuple[str, ...]
    missing_task_ids: tuple[str, ...]

    @property
    def warning(self) -> str:
        if not self.failed_task_ids:
            return ""
        return "dependency_unavailable:" + ",".join(self.failed_task_ids)

    def failure_status(self, task: TaskSpec) -> TaskStatus:
        """Preserve legacy semantics: required descendant blocks, optional skips."""

        return failure_status_for_required_task(task.required)

    def failure_result(self, task: TaskSpec) -> TaskResult:
        if self.missing_task_ids:
            raise FrontierStateConflictError(
                "cannot finalize a task with unresolved dependencies: "
                + ", ".join(self.missing_task_ids)
            )
        if not self.failed_task_ids:
            raise FrontierStateConflictError("dependency projection has no failure")
        return TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=self.failure_status(task),
            error_code="dependency_unavailable",
            unmet_requirements=list(self.failed_task_ids),
        )


def ready_tasks(
    plan: ValidatedTaskPlan,
    results: Mapping[str, TaskResult | Mapping[str, Any]]
    | Iterable[TaskResult | Mapping[str, Any]],
    statuses: Mapping[str, TaskStatus | str] | None = None,
) -> tuple[str, ...]:
    """Return stable task IDs whose dependencies have terminal results.

    An unrelated failed result is deliberately irrelevant; only dependencies
    declared by each candidate task participate in frontier calculation.
    """

    result_by_id = _result_map(results)
    status_by_id = {
        str(task_id).strip(): _status(value)
        for task_id, value in (statuses or {}).items()
        if str(task_id).strip()
    }
    for task_id, result in result_by_id.items():
        explicit = status_by_id.get(task_id)
        if explicit is not None and explicit != result.status:
            raise FrontierStateConflictError(
                f"result/status mismatch for task_id={task_id}: "
                f"{result.status.value} != {explicit.value}"
            )

    ready: list[str] = []
    for task in sorted(plan.tasks, key=lambda item: item.task_id):
        own_status = status_by_id.get(task.task_id)
        if task.task_id in result_by_id:
            continue
        if own_status is not None and own_status not in _DISPATCHABLE_STATUSES:
            continue

        dependencies_complete = True
        for dependency_id in task.depends_on:
            dependency_result = result_by_id.get(dependency_id)
            dependency_status = status_by_id.get(dependency_id)
            if dependency_result is None:
                dependencies_complete = False
                break
            if dependency_status is None:
                dependency_status = dependency_result.status
            if dependency_status not in TERMINAL_TASK_STATUSES:
                dependencies_complete = False
                break
        if dependencies_complete:
            ready.append(task.task_id)
    return tuple(ready)


def dependency_results(
    task: TaskSpec,
    results: Mapping[str, TaskResult | Mapping[str, Any]]
    | Iterable[TaskResult | Mapping[str, Any]],
) -> DependencyProjection:
    """Project declared upstream TaskResults and refs, never raw task outputs."""

    result_by_id = _result_map(results)
    projected = {
        dependency_id: result_by_id[dependency_id]
        for dependency_id in task.depends_on
        if dependency_id in result_by_id
    }
    missing = tuple(
        dependency_id
        for dependency_id in task.depends_on
        if dependency_id not in result_by_id
    )
    failed = tuple(
        sorted(
            dependency_id
            for dependency_id in task.depends_on
            if dependency_id in projected
            and projected[dependency_id].status not in _SUCCESS_STATUSES
        )
    )
    artifacts = reduce_artifact_refs(
        (),
        (
            ref
            for result in projected.values()
            for ref in result.artifact_refs
        ),
    )
    evidence = reduce_evidence_refs(
        (),
        (
            ref
            for result in projected.values()
            for ref in result.evidence_refs
        ),
    )
    return DependencyProjection(
        results=MappingProxyType(projected),
        artifact_refs=artifacts,
        evidence_refs=evidence,
        failed_task_ids=failed,
        missing_task_ids=missing,
    )


__all__ = [
    "DependencyProjection",
    "FrontierStateConflictError",
    "dependency_results",
    "ready_tasks",
]
