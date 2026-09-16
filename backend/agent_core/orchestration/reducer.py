from __future__ import annotations

from collections.abc import Iterable

from backend.models.agent_tasks import TaskResult


class TaskResultConflictError(ValueError):
    pass


def _key(result: TaskResult) -> tuple[str, str, int]:
    return (result.task_id, result.attempt_id, result.result_version)


def _sort_key(result: TaskResult) -> tuple[str, int, int, str]:
    return (
        result.task_id,
        result.attempt_ordinal,
        result.result_version,
        result.attempt_id,
    )


def reduce_task_results(
    existing: Iterable[TaskResult],
    incoming: Iterable[TaskResult],
) -> tuple[TaskResult, ...]:
    merged: dict[tuple[str, str, int], TaskResult] = {}
    for result in [*existing, *incoming]:
        key = _key(result)
        previous = merged.get(key)
        if previous is None:
            merged[key] = result.model_copy(deep=True)
            continue
        if previous.content_hash != result.content_hash:
            raise TaskResultConflictError(
                "conflicting task result for "
                f"task={result.task_id}, attempt={result.attempt_id}, "
                f"version={result.result_version}"
            )
    return tuple(sorted(merged.values(), key=_sort_key))


__all__ = ["TaskResultConflictError", "reduce_task_results"]
