from __future__ import annotations

import random

import pytest

from backend.agent_core.orchestration.reducer import (
    TaskResultConflictError,
    reduce_task_results,
)
from backend.models.agent_tasks import TaskResult


def _result(
    task_id: str,
    attempt_id: str,
    *,
    ordinal: int = 1,
    version: int = 1,
    warning: str = "",
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        attempt_id=attempt_id,
        attempt_ordinal=ordinal,
        result_version=version,
        status="succeeded",
        warnings=[warning] if warning else [],
        source_versions={f"source:{task_id}": "v1"},
    )


def test_two_instances_of_same_role_are_preserved_by_task_id() -> None:
    a = _result("document-a", "attempt-1")
    b = _result("document-b", "attempt-1")

    reduced = reduce_task_results((), (a, b))

    assert [item.task_id for item in reduced] == ["document-a", "document-b"]
    assert len(reduced) == 2


def test_reducer_is_independent_of_completion_order() -> None:
    results = [
        _result("document-b", "attempt-1"),
        _result("research", "attempt-1"),
        _result("document-a", "attempt-1"),
        _result("document-a", "attempt-2", ordinal=2),
    ]
    expected = [
        (item.task_id, item.attempt_ordinal, item.result_version, item.content_hash)
        for item in reduce_task_results((), results)
    ]

    rng = random.Random(17)
    for _ in range(20):
        shuffled = list(results)
        rng.shuffle(shuffled)
        actual = [
            (item.task_id, item.attempt_ordinal, item.result_version, item.content_hash)
            for item in reduce_task_results((), shuffled)
        ]
        assert actual == expected


def test_duplicate_same_hash_is_idempotent() -> None:
    result = _result("document-a", "attempt-1")
    duplicate = TaskResult.model_validate(result.model_dump(mode="json"))

    reduced = reduce_task_results((result,), (duplicate,))

    assert len(reduced) == 1
    assert reduced[0].content_hash == result.content_hash


def test_same_task_attempt_version_with_different_hash_is_conflict() -> None:
    first = _result("document-a", "attempt-1")
    different = _result(
        "document-a",
        "attempt-1",
        warning="different normalized result",
    )

    with pytest.raises(TaskResultConflictError, match="conflicting task result"):
        reduce_task_results((first,), (different,))
