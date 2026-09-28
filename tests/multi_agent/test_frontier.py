from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.agent_core.orchestration.frontier import (
    dependency_results,
    ready_tasks,
)
from backend.agent_core.orchestration.parallel_executor import ParallelTaskGraphExecutor
from backend.models.agent_tasks import TaskResult, TaskRole, TaskStatus
from tests.multi_agent.scheduler_support import FunctionExecutor, plan, scope, success

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "native-frontier-cases.json"
_FIXTURES: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _schedule_cases() -> list[dict[str, Any]]:
    return [item for item in _FIXTURES["cases"] if "tasks" in item]


def _plan_for(case: dict[str, Any]):
    return plan(
        tuple(case["tasks"]),
        dependencies=case.get("dependencies", {}),
    )


def _pure_synthesis(case: dict[str, Any]):
    task_plan = _plan_for(case)
    pending = task_plan.task_map()
    results: dict[str, TaskResult] = {}
    outputs: dict[str, Any] = {}
    failures = set(case.get("fail", ()))

    while pending:
        frontier = ready_tasks(
            task_plan,
            results,
            {task_id: result.status for task_id, result in results.items()},
        )
        assert frontier, "validated fixture must have an executable frontier"
        for task_id in frontier:
            task = pending.pop(task_id)
            projection = dependency_results(task, results)
            if projection.failed_task_ids:
                result = projection.failure_result(task)
            elif task_id in failures:
                result = TaskResult(
                    task_id=task_id,
                    attempt_id=f"{task_id}:1",
                    status=TaskStatus.FAILED,
                    error_code="RuntimeError",
                )
            else:
                execution = success(task_id)
                result = execution.result
                outputs[task_id] = execution.output
            results[task_id] = result
    return tuple(results.values()), outputs


def _result_summary(results: tuple[TaskResult, ...] | list[TaskResult]):
    return {
        result.task_id: (
            result.status.value,
            result.error_code,
            tuple(result.unmet_requirements),
            tuple(result.warnings),
            result.content_hash,
        )
        for result in results
    }


@pytest.mark.parametrize("case", _schedule_cases(), ids=lambda case: case["id"])
def test_pure_frontier_synthesis_matches_legacy_executor(case: dict[str, Any]) -> None:
    task_plan = _plan_for(case)
    failures = set(case.get("fail", ()))

    def execute(task):
        if task.task_id in failures:
            raise RuntimeError("synthetic failure")
        return success(task.task_id)

    legacy = ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: FunctionExecutor(execute)}
    ).execute(plan=task_plan, scope=scope(), run_id=f"frontier-{case['id']}")
    pure_results, pure_outputs = _pure_synthesis(case)

    assert _result_summary(legacy.results) == _result_summary(pure_results)
    assert legacy.outputs == pure_outputs
    assert {task_id: status for task_id, status in case["expected_statuses"].items()} == {
        task_id: status[0] for task_id, status in _result_summary(legacy.results).items()
    }


def test_ready_frontier_is_sorted_and_an_unrelated_failure_does_not_block() -> None:
    task_plan = _plan_for(_schedule_cases()[2])
    results = {
        "b": TaskResult(task_id="b", attempt_id="b:1", status=TaskStatus.FAILED)
    }

    assert ready_tasks(task_plan, results) == ("a", "d")

    results["a"] = TaskResult(task_id="a", attempt_id="a:1", status=TaskStatus.SUCCEEDED)
    assert ready_tasks(task_plan, results) == ("c", "d")


def test_dependency_projection_contains_only_declared_typed_results_and_refs() -> None:
    from backend.models.agent_artifacts import ArtifactKind, ArtifactRef, EvidenceRef

    task_plan = _plan_for(_schedule_cases()[1])
    task = task_plan.task_map()["b"]
    upstream = TaskResult(
        task_id="a",
        attempt_id="a:1",
        status=TaskStatus.SUCCEEDED,
        artifact_refs=[
            ArtifactRef(
                artifact_id="analysis-a",
                version=1,
                kind=ArtifactKind.DOCUMENT_ANALYSIS,
                content_hash="hash-a",
            )
        ],
        evidence_refs=[
            EvidenceRef(
                evidence_id="evidence-a",
                source_id="paper-a",
                source_type="document",
                source_version="v1",
                source_hash="source-hash-a",
            )
        ],
    )
    unrelated = TaskResult(
        task_id="unrelated",
        attempt_id="unrelated:1",
        status=TaskStatus.SUCCEEDED,
    )

    projection = dependency_results(task, {"a": upstream, "unrelated": unrelated})

    assert set(projection.results) == {"a"}
    assert [item.artifact_id for item in projection.artifact_refs] == ["analysis-a"]
    assert [item.evidence_id for item in projection.evidence_refs] == ["evidence-a"]
    assert projection.missing_task_ids == ()
    assert "unrelated" not in repr(projection)


def test_unresolved_dependency_is_not_ready_or_falsely_projected() -> None:
    task_plan = _plan_for(_schedule_cases()[1])
    task = task_plan.task_map()["b"]

    assert ready_tasks(task_plan, {}) == ("a",)
    projection = dependency_results(task, {})
    assert projection.missing_task_ids == ("a",)
    assert not projection.results


def test_optional_task_failure_is_a_skip_with_stable_reason() -> None:
    task_plan = _plan_for(_schedule_cases()[1])
    task = task_plan.task_map()["b"].model_copy(update={"required": False})
    failed_parent = TaskResult(
        task_id="a", attempt_id="a:1", status=TaskStatus.FAILED
    )

    projection = dependency_results(task, {"a": failed_parent})
    result = projection.failure_result(task)

    assert projection.warning == "dependency_unavailable:a"
    assert result.status is TaskStatus.SKIPPED
    assert result.error_code == "dependency_unavailable"
    assert result.unmet_requirements == ["a"]

    base_plan = _plan_for(_schedule_cases()[1])
    optional_plan = base_plan.model_copy(
        update={
            "tasks": [
                item.model_copy(update={"required": False})
                if item.task_id == "b"
                else item
                for item in base_plan.tasks
            ]
        }
    )

    def fail_parent(task):
        if task.task_id == "a":
            raise RuntimeError("synthetic failure")
        return success(task.task_id)

    legacy = ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: FunctionExecutor(fail_parent)}
    ).execute(plan=optional_plan, scope=scope(), run_id="optional-failure")
    actual_optional = next(item for item in legacy.results if item.task_id == "b")
    assert actual_optional.status is result.status
    assert actual_optional.error_code == result.error_code
    assert actual_optional.unmet_requirements == result.unmet_requirements
