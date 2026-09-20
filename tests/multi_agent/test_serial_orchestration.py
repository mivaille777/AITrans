from __future__ import annotations

from collections.abc import Mapping

from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.orchestration.serial_executor import (
    SerialTaskGraphExecutor,
    SpecialistExecution,
)
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskRole, TaskStatus


class Executor:
    def __init__(self, calls: list[str], *, direct: bool = False) -> None:
        self.calls = calls
        self.direct = direct

    def execute(self, *, task, scope, dependency_results: Mapping, memory_snapshot):
        assert task.scope_ref == scope.scope_ref
        assert memory_snapshot["snapshot_id"] == "memory-1"
        assert set(dependency_results) == set(task.depends_on)
        self.calls.append(task.task_id)
        return SpecialistExecution(
            result=TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:1",
                status=TaskStatus.SUCCEEDED,
            ),
            output=f"output:{task.task_id}",
            direct_delivery=self.direct,
        )


def test_serial_topology_preserves_two_document_instances_by_task_id() -> None:
    scope = ScopeContext.issue(
        scope_revision="serial",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    plan = ValidatedSupervisorPlanner().plan(
        route=OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            primary_role=TaskRole.RESEARCH,
            reason_code="test",
        ),
        objective="compare",
        scope=scope,
    )
    calls: list[str] = []
    executor = Executor(calls)

    run = SerialTaskGraphExecutor(
        {TaskRole.DOCUMENT: executor, TaskRole.RESEARCH: executor}
    ).execute(
        plan=plan,
        scope=scope,
        memory_snapshot={"snapshot_id": "memory-1"},
    )

    assert calls == ["document-1", "document-2", "research-1"]
    assert [item.task_id for item in run.results] == calls
    assert set(run.outputs) == set(calls)


def test_completed_specialist_output_can_be_marked_for_direct_delivery() -> None:
    scope = ScopeContext.issue(scope_revision="single", allowed_document_ids=["doc-a"])
    plan = ValidatedSupervisorPlanner().plan(
        route=OrchestrationRoute(
            lane=OrchestrationLane.SINGLE,
            primary_role=TaskRole.DOCUMENT,
            reason_code="test",
        ),
        objective="summarize",
        scope=scope,
    )
    calls: list[str] = []

    run = SerialTaskGraphExecutor(
        {TaskRole.DOCUMENT: Executor(calls, direct=True)}
    ).execute(
        plan=plan,
        scope=scope,
        memory_snapshot={"snapshot_id": "memory-1"},
    )

    assert run.direct_delivery is True
    assert run.direct_output == "output:document-1"


def test_intermediate_direct_output_never_bypasses_requested_leaf_task() -> None:
    scope = ScopeContext.issue(
        scope_revision="writer-workflow",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    plan = ValidatedSupervisorPlanner().plan(
        route=OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            primary_role=TaskRole.WRITER,
            reason_code="test",
        ),
        objective="draft a section",
        scope=scope,
    )
    calls: list[str] = []

    run = SerialTaskGraphExecutor(
        {
            TaskRole.DOCUMENT: Executor(calls, direct=True),
            TaskRole.RESEARCH: Executor(calls, direct=True),
            TaskRole.WRITER: Executor(calls, direct=False),
        }
    ).execute(
        plan=plan,
        scope=scope,
        memory_snapshot={"snapshot_id": "memory-1"},
    )

    assert calls == ["document-1", "document-2", "research-1", "writer-1"]
    assert run.direct_delivery is False
    assert run.direct_output is None
