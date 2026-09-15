from __future__ import annotations

from backend.agent_core.events import AgentEventType
from backend.agent_core.multi_agent.context import KnowledgeInjector
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService


class _FakeKnowledgeRuntime:
    def build_context(self, query: str, top_k: int = 5):
        return {
            "query": query,
            "context": "[paper-1] Grounded collaboration evidence (paper)",
            "citations": [
                {
                    "id": "paper-1",
                    "title": "Grounded collaboration evidence",
                    "source_type": "paper",
                    "score": 0.95,
                }
            ],
        }


class _MainWorkflow:
    def __init__(self) -> None:
        self.seen_context_before = ""
        self.seen_multi_agent_context = None

    def run_with_events(self, state, emit, *, control=None):
        self.seen_context_before = str(state.browser_context.get("context_before", ""))
        self.seen_multi_agent_context = state.browser_context.get("multi_agent_context")
        emit(
            AgentEventType.PLAN_READY,
            {"action": "answer", "source": "main_workflow"},
        )
        state.apply_plan({"action": "answer", "user_visible_reason": "main workflow"})
        state.apply_response(
            {
                "status": "completed",
                "output_text": "Final answer from canonical workflow",
                "provider": "test",
                "model": "test",
            }
        )
        return state


def _bridge() -> MultiAgentRuntimeBridge:
    service = MultiAgentWorkspaceService(
        knowledge_injector=KnowledgeInjector(_FakeKnowledgeRuntime()),
    )
    return MultiAgentRuntimeBridge(service)


def test_stage5_8_collaboration_runs_inside_canonical_runtime():
    workflow = _MainWorkflow()
    runtime = AgentRuntime(
        collaboration_adapter=_bridge(),
        workflow_adapter=workflow,
    )
    state = AgentState(
        run_id="run-stage5-8",
        trace_id="trace-stage5-8",
        session_id="session-stage5-8",
        user_input="阅读这篇论文并翻译实验章节",
        selected_text="paper text",
        browser_context={"context_before": "original reading context"},
    )

    result = runtime.execute(state)

    assert result.response["output_text"] == "Final answer from canonical workflow"
    assert result.browser_context["multi_agent_active"] is True
    assert workflow.seen_multi_agent_context is not None
    assert workflow.seen_multi_agent_context["agents"] == [
        "research",
        "reading",
        "translation",
    ]
    assert "Grounded collaboration evidence" in workflow.seen_context_before
    assert "original reading context" in workflow.seen_context_before

    event_types = [event.event_type for event in runtime.events]
    assert event_types[0] == AgentEventType.AGENT_START
    assert AgentEventType.MULTI_AGENT_STARTED in event_types
    assert AgentEventType.MULTI_AGENT_PLAN_READY in event_types
    assert AgentEventType.MULTI_AGENT_KNOWLEDGE_READY in event_types
    assert AgentEventType.MULTI_AGENT_CONTEXT_READY in event_types
    assert AgentEventType.MULTI_AGENT_SPECIALIST_COMPLETED in event_types
    assert AgentEventType.MULTI_AGENT_COMPLETED in event_types
    assert event_types.index(AgentEventType.MULTI_AGENT_COMPLETED) < event_types.index(
        AgentEventType.PLAN_READY
    )
    assert event_types[-1] == AgentEventType.AGENT_END
    assert all(event.run_id == "run-stage5-8" for event in runtime.events)
    assert all(event.trace_id == "trace-stage5-8" for event in runtime.events)


def test_stage5_8_single_role_request_stays_on_primary_path():
    workflow = _MainWorkflow()
    runtime = AgentRuntime(
        collaboration_adapter=_bridge(),
        workflow_adapter=workflow,
    )
    state = AgentState(
        user_input="翻译这一段",
        selected_text="paper text",
    )

    result = runtime.execute(state)

    assert result.response["status"] == "completed"
    assert "multi_agent_context" not in result.browser_context
    assert not any(
        event.event_type.value.startswith("multi_agent_")
        for event in runtime.events
    )
