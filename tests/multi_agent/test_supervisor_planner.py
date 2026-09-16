from __future__ import annotations

import pytest

from backend.agent_core.orchestration.planner import (
    SupervisorPlanningError,
    ValidatedSupervisorPlanner,
)
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import ScopeContext, TaskRole


def _scope() -> ScopeContext:
    return ScopeContext.issue(
        scope_revision="workspace-a-plan",
        workspace_id="workspace-a",
        allowed_document_ids=["doc-a", "doc-b"],
    )


def test_deterministic_workflow_has_typed_dependencies_and_artifacts() -> None:
    plan = ValidatedSupervisorPlanner().plan(
        route=OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            primary_role=TaskRole.RESEARCH,
            reason_code="test",
        ),
        objective="compare papers",
        scope=_scope(),
    )

    assert plan is not None
    assert [task.task_id for task in plan.tasks] == [
        "document-1",
        "document-2",
        "research-1",
    ]
    research = plan.task_map()["research-1"]
    assert research.depends_on == ["document-1", "document-2"]
    assert {item.kind for item in research.input_refs} == {
        ArtifactKind.DOCUMENT_ANALYSIS
    }
    assert all(task.scope_ref == _scope().scope_ref for task in plan.tasks)


def test_provider_plan_gets_only_one_repair_and_cannot_forge_scope() -> None:
    calls: list[dict] = []
    scope = _scope()

    def provider(**kwargs):
        calls.append(kwargs)
        scope_ref = "forged" if len(calls) == 1 else scope.scope_ref
        return {
            "plan_id": "provider-plan",
            "plan_revision": 1,
            "scope_ref": scope_ref,
            "tasks": [
                {
                    "task_id": "document-1",
                    "role": "document",
                    "objective": "analyze",
                    "required": True,
                    "expected_output_kind": "document_analysis",
                    "scope_ref": scope_ref,
                    "allowed_tools": ["inspect_reading_context"],
                }
            ],
        }

    plan = ValidatedSupervisorPlanner(provider=provider).plan(
        route=OrchestrationRoute(
            lane=OrchestrationLane.SINGLE,
            primary_role=TaskRole.DOCUMENT,
            reason_code="test",
        ),
        objective="analyze",
        scope=scope,
    )

    assert plan is not None
    assert len(calls) == 2
    assert calls[1]["repair_error"]
    assert plan.scope_ref == scope.scope_ref


def test_provider_plan_fails_after_one_repair_attempt() -> None:
    calls = 0

    def provider(**_kwargs):
        nonlocal calls
        calls += 1
        return {"invalid": True}

    with pytest.raises(SupervisorPlanningError, match="one repair"):
        ValidatedSupervisorPlanner(provider=provider).plan(
            route=OrchestrationRoute(
                lane=OrchestrationLane.SINGLE,
                primary_role=TaskRole.DOCUMENT,
                reason_code="test",
            ),
            objective="analyze",
            scope=_scope(),
        )

    assert calls == 2


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        ("Create a paper outline", ArtifactKind.OUTLINE),
        ("Draft the discussion section", ArtifactKind.MANUSCRIPT_SECTION),
        ("Revise only the second paragraph", ArtifactKind.REVISION),
    ],
)
def test_writer_plan_declares_the_requested_typed_artifact(
    objective: str,
    expected: ArtifactKind,
) -> None:
    plan = ValidatedSupervisorPlanner().plan(
        route=OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            primary_role=TaskRole.WRITER,
            reason_code="test",
        ),
        objective=objective,
        scope=_scope(),
    )

    assert plan is not None
    assert plan.task_map()["writer-1"].expected_output_kind is expected
