from types import SimpleNamespace

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult


def test_agent_state_contract_separates_execution_conversation_and_reading_context():
    state = AgentState(
        session_id="session-1",
        user_input="Explain this",
        selected_text="Gaussian processes are probabilistic models.",
        browser_context={
            "conversation_id": "conv-1",
            "style": "academic",
            "translated_text": "高斯过程是概率模型。",
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_url": "https://example.com/paper",
            "resource_title": "Control Paper",
            "section_heading": "Method",
            "context_before": "Previous paragraph",
            "context_after": "Next paragraph",
            "source_kind": "browser_dom",
            "request_id": 7,
        },
    )

    assert state.execution.run_id == state.run_id
    assert state.execution.trace_id == state.trace_id
    assert state.execution.session_id == "session-1"
    assert state.execution.request_id == 7
    assert state.conversation.conversation_id == "conv-1"
    assert state.request.user_input == "Explain this"
    assert state.request.style == "academic"
    assert state.reading_context.source_text.startswith("Gaussian processes")
    assert state.reading_context.resource_title == "Control Paper"
    assert state.reading_context.source_kind == "browser_dom"
    assert state.route.kind == "unresolved"
    assert state.plan.mode == "none"
    assert state.response_state.status == "idle"

    payload = state.model_dump()
    assert payload["selected_text"] == state.selected_text
    assert payload["reading_context"]["resource_title"] == "Control Paper"


def test_reading_context_can_change_without_replacing_conversation_or_run():
    state = AgentState(
        user_input="Explain this",
        selected_text="first selection",
        browser_context={
            "conversation_id": "conv-1",
            "resource_title": "Paper",
            "source_kind": "browser_dom",
        },
    )
    run_id = state.run_id
    trace_id = state.trace_id

    state.apply_reading_context(
        {
            **state.browser_context,
            "source_text": "second selection",
            "section_heading": "Results",
        }
    )

    assert state.run_id == run_id
    assert state.trace_id == trace_id
    assert state.conversation.conversation_id == "conv-1"
    assert state.selected_text == "second selection"
    assert state.reading_context.source_text == "second selection"
    assert state.reading_context.section_heading == "Results"


def test_new_agent_run_can_keep_same_conversation_id():
    first = AgentState(
        user_input="first question",
        selected_text="selection",
        browser_context={"conversation_id": "conv-1"},
    )
    second = AgentState(
        user_input="second question",
        selected_text="selection",
        browser_context={"conversation_id": "conv-1"},
    )

    assert first.run_id != second.run_id
    assert first.trace_id != second.trace_id
    assert first.conversation.conversation_id == second.conversation.conversation_id == "conv-1"


class _FakeProductAgentService:
    def run(self, **_payload):
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="tool",
                tool_name="translate_selection",
                user_visible_reason="Translate the selected text.",
                arguments={"target_language": "zh-CN"},
            ),
            output_text="高斯过程",
            provider="fake-provider",
            model="fake-model",
            request_id=11,
            tool_result=AgentToolExecutionResult(
                tool_name="translate_selection",
                output_text="高斯过程",
                effect="compute",
                provider="fake-provider",
                model="fake-model",
                request_id=11,
                data={"target_language": "zh-CN"},
            ),
        )


def test_product_adapter_keeps_typed_contract_in_sync_with_legacy_state():
    state = AgentState(
        user_input="Translate this",
        selected_text="Gaussian Process",
        browser_context={
            "conversation_id": "conv-9",
            "target_language": "zh-CN",
            "request_id": 11,
        },
    )

    result = ProductAgentRuntimeAdapter(_FakeProductAgentService())(state)

    assert result.intent == "translate_selection"
    assert result.route.kind == "tool"
    assert result.route.source == "legacy_planner"
    assert result.route.tool_name == "translate_selection"
    assert result.plan.mode == "single_step"
    assert result.plan.steps[0].tool_name == "translate_selection"
    assert result.plan.steps[0].status == "completed"
    assert result.response_state.status == "completed"
    assert result.response_state.output_text == "高斯过程"
    assert result.response_state.ui_mode == "translation"
    assert result.conversation.conversation_id == "conv-9"


class _RoutedProductAgentService(_FakeProductAgentService):
    def run(self, **payload):
        result = super().run(**payload)
        result.route = AgentRouteDecision(
            kind="tool",
            source="deterministic",
            intent="translate_selection",
            tool_name="translate_selection",
            user_visible_reason="Translate the current reading selection.",
            arguments={"target_language": "zh-CN"},
        )
        return result


def test_product_adapter_preserves_explicit_route_source_across_state_sync():
    state = AgentState(
        user_input="翻成中文",
        selected_text="Gaussian Process",
        browser_context={"conversation_id": "conv-route", "request_id": 11},
    )

    result = ProductAgentRuntimeAdapter(_RoutedProductAgentService())(state)

    assert result.route.source == "deterministic"
    assert result.route.tool_name == "translate_selection"
    assert result.plan.steps[0].status == "completed"
    assert result.response_state.status == "completed"
    assert result.conversation.conversation_id == "conv-route"
