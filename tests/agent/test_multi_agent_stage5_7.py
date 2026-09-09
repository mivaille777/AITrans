from __future__ import annotations

from backend.agent_core.multi_agent.context import KnowledgeInjector
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService


class _FakeKnowledgeRuntime:
    def build_context(self, query: str, top_k: int = 5):
        return {
            "query": query,
            "context": "[paper-1] Grounded paper (paper)",
            "citations": [
                {
                    "id": "paper-1",
                    "title": "Grounded paper",
                    "source_type": "paper",
                    "score": 0.9,
                }
            ],
        }


def test_stage5_7_trace_covers_supervisor_knowledge_context_and_specialists():
    service = MultiAgentWorkspaceService(
        knowledge_injector=KnowledgeInjector(_FakeKnowledgeRuntime()),
    )

    run = service.run("阅读这篇论文并翻译实验章节", user_id="test-user")

    assert [item["agent"] for item in run.plan] == [
        "research",
        "reading",
        "translation",
    ]
    assert [result.agent_name for result in run.results] == [
        "research",
        "reading",
        "translation",
    ]
    assert run.context.knowledge_context
    assert len(run.context.citations) == 1
    assert sorted(run.context.intermediate_results) == [
        "reading",
        "research",
        "translation",
    ]

    actors = {event.actor for event in run.events}
    assert {
        "supervisor",
        "knowledge",
        "shared_context",
        "research",
        "reading",
        "translation",
    }.issubset(actors)

    event_types = [event.event_type for event in run.events]
    assert event_types[0] == "supervisor_started"
    assert "supervisor_planned" in event_types
    assert "knowledge_retrieval_started" in event_types
    assert "knowledge_retrieved" in event_types
    assert "shared_context_ready" in event_types
    assert event_types[-1] == "workflow_completed"


def test_stage5_7_api_route_is_registered():
    from backend.main import create_app

    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/agent/multi-agent/run/trace" in paths
