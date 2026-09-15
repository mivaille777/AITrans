from types import SimpleNamespace

import pytest

from backend.agent_core.events import AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.api.agent_dependencies import get_agent_runtime
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult


class FakeProductAgentService:
    def __init__(self) -> None:
        self.payload = None

    def run(self, *, event_sink=None, control=None, **payload):
        self.payload = payload
        plan = AgentPlan(
            action="tool",
            tool_name="translate_selection",
            user_visible_reason="Translate the current selection.",
            arguments={"target_language": "zh-CN"},
        )
        tool_result = AgentToolExecutionResult(
            tool_name="translate_selection",
            output_text="高斯过程",
            effect="compute",
            provider="fake-provider",
            model="fake-model",
            request_id=7,
            data={"target_language": "zh-CN"},
        )
        if event_sink is not None:
            event_sink(
                "plan_ready",
                {
                    "action": "tool",
                    "tool_name": "translate_selection",
                    "request_id": 7,
                },
            )
            event_sink(
                "tool_call",
                {
                    "name": "translate_selection",
                    "effect": "compute",
                    "request_id": 7,
                },
            )
            event_sink(
                "tool_result",
                {
                    "tool_name": "translate_selection",
                    "effect": "compute",
                    "provider": "fake-provider",
                    "model": "fake-model",
                    "request_id": 7,
                },
            )
        return SimpleNamespace(
            status="completed",
            plan=plan,
            output_text="高斯过程",
            provider="fake-provider",
            model="fake-model",
            request_id=7,
            tool_result=tool_result,
            route=None,
        )


class FailingProductAgentService(FakeProductAgentService):
    def run(self, *, event_sink=None, control=None, **payload):
        self.payload = payload
        raise RuntimeError("product workflow failed")


class FakeConversationService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def begin(self, state: AgentState):
        self.calls.append("begin")
        return SimpleNamespace(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            history=(("user", "Earlier question"), ("assistant", "Earlier answer")),
        )

    def apply_to_state(self, state: AgentState, run):
        self.calls.append("apply")
        return state.apply_conversation(
            conversation_id=run.conversation_id,
            history=run.history,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
            context_mode="reading",
        )

    def complete(self, run, state: AgentState) -> None:
        self.calls.append("complete")

    def fail(self, run, exc: Exception) -> None:
        self.calls.append("fail")

    def cancel(self, run) -> None:
        self.calls.append("cancel")


class FakeReadingSelectionResolver:
    pass


def make_state() -> AgentState:
    return AgentState(
        session_id="session-1",
        user_input="Translate this",
        selected_text="Gaussian Process",
        browser_context={
            "target_language": "zh-CN",
            "resource_title": "Control Paper",
            "request_id": 7,
        },
    )


def test_reading_agent_graph_compiles_explicit_react_nodes() -> None:
    graph = ReadingAgentGraph(ProductAgentRuntimeAdapter(FakeProductAgentService()))

    assert graph.node_names == (
        "prepare_conversation",
        "route_request",
        "execute_direct",
        "start_react",
        "decide_react",
        "execute_react_tool",
        "finalize_react",
        "finalize_conversation",
    )
    assert callable(graph.compiled_graph.invoke)


def test_reading_agent_graph_preserves_runtime_events_and_conversation_history() -> None:
    service = FakeProductAgentService()
    conversations = FakeConversationService()
    graph = ReadingAgentGraph(
        ProductAgentRuntimeAdapter(service, conversation_service=conversations)
    )
    runtime = AgentRuntime(
        context_provider=lambda state: dict(state.browser_context),
        workflow_adapter=graph,
    )

    result = runtime.execute(make_state())

    assert conversations.calls == ["begin", "apply", "complete"]
    assert service.payload["conversation_id"] == "conversation-1"
    assert service.payload["history"] == (
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
    )
    assert result.response["output_text"] == "高斯过程"
    assert [event.event_type for event in runtime.events] == [
        AgentEventType.AGENT_START,
        AgentEventType.CONTEXT_READY,
        AgentEventType.PLAN_READY,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.AGENT_END,
    ]


def test_reading_agent_graph_aborts_conversation_when_product_node_fails() -> None:
    conversations = FakeConversationService()
    graph = ReadingAgentGraph(
        ProductAgentRuntimeAdapter(
            FailingProductAgentService(),
            conversation_service=conversations,
        )
    )
    runtime = AgentRuntime(workflow_adapter=graph)

    with pytest.raises(RuntimeError, match="product workflow failed"):
        runtime.execute(make_state())

    assert conversations.calls == ["begin", "apply", "fail"]


def test_agent_runtime_dependency_uses_reading_agent_graph() -> None:
    runtime = get_agent_runtime(
        FakeProductAgentService(),
        FakeReadingSelectionResolver(),
    )

    assert isinstance(runtime.workflow_adapter, ReadingAgentGraph)
