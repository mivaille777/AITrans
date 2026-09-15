from __future__ import annotations

from types import SimpleNamespace

from backend.models.agent_runtime import AgentRouteDecision
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec
from backend.services.product_agent_service import ProductAgentService


TRANSLATE_TOOL = AgentToolSpec(
    name="translate_selection",
    title="Translate selection",
    description="Translate selection",
    category="translation",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={"target_language": {"type": "string", "maxLength": 64}},
)
EXPLAIN_TOOL = AgentToolSpec(
    name="explain_selection",
    title="Explain selection",
    description="Explain selection",
    category="reading",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)
SUMMARY_TOOL = AgentToolSpec(
    name="summarize_selection",
    title="Summarize selection",
    description="Summarize selection",
    category="reading",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)
SAVE_TOOL = AgentToolSpec(
    name="save_research_note",
    title="Save research note",
    description="Save research note",
    category="research",
    effect="write",
    requires_reading_context=True,
    requires_confirmation=True,
    input_schema={"user_note": {"type": "string", "maxLength": 4000}},
)


class FakeRegistry:
    def __init__(self) -> None:
        self.tools = (TRANSLATE_TOOL, EXPLAIN_TOOL, SUMMARY_TOOL, SAVE_TOOL)
        self.executions: list[tuple[str, dict]] = []

    def list_tools(self):
        return self.tools

    def get_tool(self, name: str):
        return next((tool for tool in self.tools if tool.name == name), None)

    def validate_planner_arguments(self, name: str, arguments: dict):
        spec = self.get_tool(name)
        if spec is None:
            raise KeyError(name)
        return spec.validate_planner_arguments(arguments)

    def allows_safe_retry(self, name: str) -> bool:
        spec = self.get_tool(name)
        return bool(spec and spec.effect != "write")

    def execute(self, name: str, **payload):
        self.executions.append((name, dict(payload)))
        spec = self.get_tool(name)
        assert spec is not None
        return AgentToolExecutionResult(
            tool_name=name,
            output_text=f"tool:{name}",
            effect=spec.effect,
            provider="fake-tool",
            model="fake-model",
            request_id=payload.get("request_id", 0),
            data={},
        )


class CountingSemanticRouter:
    provider_name = "semantic-provider"
    model = "semantic-model"
    prompt_id = "semantic@test"

    def __init__(self, route: AgentRouteDecision | None = None) -> None:
        self.calls = 0
        self.route_result = route or AgentRouteDecision(
            kind="answer",
            source="semantic_router",
            intent="answer",
            user_visible_reason="Answer normally.",
        )

    def route(self, **_kwargs):
        self.calls += 1
        return self.route_result


class FakeChatService:
    prompt_id = "chat@test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            output_text="final answer",
            provider="fake-chat",
            model="fake-chat-model",
            request_id=kwargs.get("request_id", 0),
        )


def _payload(message: str, **overrides):
    return {
        "session_id": "session-10-3",
        "user_message": message,
        "source_text": "Gaussian processes provide a statistical anchor.",
        "translated_text": "",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "file:///paper.pdf",
        "resource_title": "Paper",
        "section_heading": "Method",
        "context_before": "Before",
        "context_after": "After",
        "source_kind": "pdf_uia",
        "request_id": 23,
        **overrides,
    }


def test_explicit_translation_skips_semantic_router() -> None:
    registry = FakeRegistry()
    semantic = CountingSemanticRouter()
    chat = FakeChatService()
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        semantic_router=semantic,
    )
    events: list[tuple[str, dict]] = []

    result = service.run(
        event_sink=lambda event_type, payload: events.append((event_type, payload)),
        **_payload("翻译一下"),
    )

    assert semantic.calls == 0
    assert result.route is not None
    assert result.route.source == "deterministic"
    assert result.plan.tool_name == "translate_selection"
    assert registry.executions[0][0] == "translate_selection"
    plan_event = events[0][1]
    assert plan_event["route_source"] == "deterministic"
    assert plan_event["llm_called"] is False


def test_explicit_target_language_reaches_tool_without_llm_routing() -> None:
    registry = FakeRegistry()
    semantic = CountingSemanticRouter()
    service = ProductAgentService(
        registry=registry,
        chat_service=FakeChatService(),
        semantic_router=semantic,
    )

    service.run(**_payload("翻成英文"))

    assert semantic.calls == 0
    assert registry.executions[0][1]["target_language"] == "en"


def test_explicit_explain_and_summary_skip_semantic_router() -> None:
    registry = FakeRegistry()
    semantic = CountingSemanticRouter()
    service = ProductAgentService(
        registry=registry,
        chat_service=FakeChatService(),
        semantic_router=semantic,
    )

    service.run(**_payload("解释一下"))
    service.run(**_payload("总结一下"))

    assert semantic.calls == 0
    assert [name for name, _ in registry.executions] == [
        "explain_selection",
        "summarize_selection",
    ]


def test_explicit_save_note_skips_semantic_router_but_keeps_confirmation_gate() -> None:
    registry = FakeRegistry()
    semantic = CountingSemanticRouter()
    service = ProductAgentService(
        registry=registry,
        chat_service=FakeChatService(),
        semantic_router=semantic,
    )

    result = service.run(**_payload("保存成笔记"))

    assert semantic.calls == 0
    assert result.status == "confirmation_required"
    assert result.route is not None and result.route.source == "deterministic"
    assert registry.executions == []


def test_ambiguous_question_calls_semantic_router_once() -> None:
    registry = FakeRegistry()
    semantic = CountingSemanticRouter()
    chat = FakeChatService()
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        semantic_router=semantic,
    )
    events: list[tuple[str, dict]] = []

    result = service.run(
        event_sink=lambda event_type, payload: events.append((event_type, payload)),
        **_payload("为什么作者这里选择高斯过程而不是直接搜索参数？"),
    )

    assert semantic.calls == 1
    assert result.route is not None
    assert result.route.source == "semantic_router"
    assert result.plan.action == "answer"
    assert len(chat.calls) == 1
    assert events[0][1]["route_source"] == "semantic_router"
    assert events[0][1]["llm_called"] is True
