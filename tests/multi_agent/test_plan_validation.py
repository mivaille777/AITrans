from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agent_core.orchestration.roles import RoleRegistry
from backend.agent_core.orchestration.validation import (
    TaskPlanValidationError,
    validate_task_plan,
)
from backend.models.agent_tasks import (
    ScopeContext,
    TaskInputRef,
    TaskSpec,
    ValidatedTaskPlan,
)


def _scope() -> ScopeContext:
    return ScopeContext.issue(
        profile_id="profile-1",
        workspace_id="workspace-a",
        scope_revision="scope-1",
        allowed_document_ids=["paper-a", "paper-b"],
    )


def _doc(task_id: str, scope: ScopeContext, document_id: str) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        role="document",
        objective=f"Analyze {document_id}",
        required=True,
        expected_output_kind="document_analysis",
        acceptance_criteria=["Preserve source coverage."],
        scope_ref=scope.scope_ref,
        allowed_tools=["inspect_reading_context"],
        budget_ref="budget-1",
        plan_revision=1,
        target_source_ids=[document_id],
    )


def test_valid_plan_supports_two_document_instances_and_typed_dependency() -> None:
    scope = _scope()
    a = _doc("doc-a", scope, "paper-a")
    b = _doc("doc-b", scope, "paper-b")
    compare = TaskSpec(
        task_id="compare",
        role="research",
        objective="Compare the two analyses.",
        depends_on=["doc-a", "doc-b"],
        required=True,
        input_refs=[
            TaskInputRef(
                artifact_id="analysis-a",
                version=1,
                kind="document_analysis",
                producer_task_id="doc-a",
            ),
            TaskInputRef(
                artifact_id="analysis-b",
                version=1,
                kind="document_analysis",
                producer_task_id="doc-b",
            ),
        ],
        expected_output_kind="comparison",
        acceptance_criteria=["Every comparison cell keeps source evidence."],
        scope_ref=scope.scope_ref,
        allowed_tools=["analyze_cross_document_research"],
        budget_ref="budget-1",
        plan_revision=1,
    )
    plan = ValidatedTaskPlan(
        plan_id="plan-1",
        scope_ref=scope.scope_ref,
        budget_ref="budget-1",
        tasks=[a, b, compare],
    )

    assert validate_task_plan(plan, scope=scope, role_registry=RoleRegistry()) is plan
    assert [task.task_id for task in plan.tasks[:2]] == ["doc-a", "doc-b"]


def test_cycle_is_rejected() -> None:
    scope = _scope()
    a = _doc("a", scope, "paper-a").model_copy(update={"depends_on": ["b"]})
    b = _doc("b", scope, "paper-b").model_copy(update={"depends_on": ["a"]})

    with pytest.raises(ValidationError, match="acyclic"):
        ValidatedTaskPlan(
            plan_id="cycle",
            scope_ref=scope.scope_ref,
            budget_ref="budget-1",
            tasks=[a, b],
        )


def test_duplicate_task_id_is_rejected() -> None:
    scope = _scope()
    with pytest.raises(ValidationError, match="unique"):
        ValidatedTaskPlan(
            plan_id="duplicates",
            scope_ref=scope.scope_ref,
            budget_ref="budget-1",
            tasks=[
                _doc("same", scope, "paper-a"),
                _doc("same", scope, "paper-b"),
            ],
        )


def test_unknown_role_is_rejected_by_typed_contract() -> None:
    scope = _scope()
    with pytest.raises(ValidationError):
        TaskSpec(
            task_id="mystery",
            role="general",
            objective="Do something.",
            required=True,
            expected_output_kind="document_analysis",
            scope_ref=scope.scope_ref,
        )


def test_role_tool_escalation_is_rejected() -> None:
    scope = _scope()
    escalated = _doc("doc-a", scope, "paper-a").model_copy(
        update={"allowed_tools": ["save_knowledge_card"]}
    )
    plan = ValidatedTaskPlan(
        plan_id="bad-tools",
        scope_ref=scope.scope_ref,
        budget_ref="budget-1",
        tasks=[escalated],
    )

    with pytest.raises(TaskPlanValidationError, match="not allowed"):
        validate_task_plan(plan, scope=scope)


def test_forged_scope_reference_is_rejected() -> None:
    authoritative = _scope()
    forged = ScopeContext.issue(
        profile_id="profile-1",
        workspace_id="workspace-b",
        scope_revision="scope-1",
        allowed_document_ids=["private-b"],
    )
    task = _doc("doc-a", forged, "private-b")
    plan = ValidatedTaskPlan(
        plan_id="forged",
        scope_ref=forged.scope_ref,
        budget_ref="budget-1",
        tasks=[task],
    )

    with pytest.raises(TaskPlanValidationError, match="authoritative"):
        validate_task_plan(plan, scope=authoritative)


def test_input_artifact_type_must_match_declared_producer_output() -> None:
    scope = _scope()
    producer = _doc("doc-a", scope, "paper-a")
    consumer = TaskSpec(
        task_id="writer",
        role="writer",
        objective="Draft from the analysis.",
        depends_on=["doc-a"],
        required=True,
        input_refs=[
            TaskInputRef(
                artifact_id="analysis-a",
                version=1,
                kind="comparison",
                producer_task_id="doc-a",
            )
        ],
        expected_output_kind="manuscript_section",
        scope_ref=scope.scope_ref,
        allowed_tools=["polish_selection"],
        budget_ref="budget-1",
        plan_revision=1,
    )
    plan = ValidatedTaskPlan(
        plan_id="wrong-input-kind",
        scope_ref=scope.scope_ref,
        budget_ref="budget-1",
        tasks=[producer, consumer],
    )

    with pytest.raises(TaskPlanValidationError, match="producer declares"):
        validate_task_plan(plan, scope=scope)


def test_plan_cannot_carry_profile_workspace_or_model_authority() -> None:
    scope = _scope()
    with pytest.raises(ValidationError):
        ValidatedTaskPlan.model_validate(
            {
                "plan_id": "authority-forgery",
                "scope_ref": scope.scope_ref,
                "budget_ref": "budget-1",
                "profile_id": "profile-evil",
                "workspace_id": "workspace-evil",
                "model": "model-evil",
                "tasks": [_doc("doc-a", scope, "paper-a").model_dump(mode="json")],
            }
        )


def test_document_task_cannot_target_an_in_scope_note_as_a_document() -> None:
    scope = ScopeContext.issue(
        profile_id="profile-1",
        workspace_id="workspace-a",
        scope_revision="mixed-sources",
        allowed_document_ids=["paper-a"],
        allowed_note_ids=["note-a"],
    )
    task = _doc("doc-a", scope, "paper-a").model_copy(
        update={"target_source_ids": ["note-a"]}
    )
    plan = ValidatedTaskPlan(
        plan_id="note-as-document",
        scope_ref=scope.scope_ref,
        budget_ref="budget-1",
        tasks=[task],
    )

    with pytest.raises(TaskPlanValidationError, match="non-document"):
        validate_task_plan(plan, scope=scope)
