from __future__ import annotations

from backend.agent_core.orchestration.router import ResearchTaskRouter
from backend.models.agent_orchestration import OrchestrationLane
from backend.models.agent_tasks import TaskRole


def test_selected_translation_stays_fast_even_in_force_mode() -> None:
    route = ResearchTaskRouter().route(
        "翻译这段文字",
        {"source_text": "Gaussian process"},
        mode="force",
    )

    assert route.lane is OrchestrationLane.FAST
    assert route.primary_role is None


def test_single_document_understanding_uses_one_document_specialist() -> None:
    route = ResearchTaskRouter().route(
        "总结这篇论文的方法",
        {"knowledge_document_ids": ["doc-a"]},
    )

    assert route.lane is OrchestrationLane.SINGLE
    assert route.primary_role is TaskRole.DOCUMENT


def test_cross_document_comparison_uses_research_workflow() -> None:
    route = ResearchTaskRouter().route(
        "比较两篇论文的实验结果",
        {"knowledge_document_ids": ["doc-a", "doc-b"]},
    )

    assert route.lane is OrchestrationLane.WORKFLOW
    assert route.primary_role is TaskRole.RESEARCH


def test_scoped_writing_request_uses_writer_workflow() -> None:
    route = ResearchTaskRouter().route(
        "基于这些论文起草 Related Work 章节",
        {"knowledge_document_ids": ["doc-a", "doc-b"]},
    )

    assert route.lane is OrchestrationLane.WORKFLOW
    assert route.primary_role is TaskRole.WRITER


def test_off_mode_disables_specialists_without_changing_scope() -> None:
    route = ResearchTaskRouter().route(
        "比较论文",
        {"knowledge_document_ids": ["doc-a", "doc-b"]},
        mode="off",
    )

    assert route.lane is OrchestrationLane.FAST
    assert route.reason_code == "multi_agent_disabled"


def test_comparison_without_two_sources_reports_missing_information() -> None:
    route = ResearchTaskRouter().route("比较这些论文", {})

    assert route.lane is OrchestrationLane.WORKFLOW
    assert route.missing_information == ["at_least_two_documents"]
