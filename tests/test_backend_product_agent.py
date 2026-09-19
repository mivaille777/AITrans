from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import AIResponseError
from backend.agent_core.exceptions import AgentToolError
from backend.api.dependencies import get_product_agent_service
from backend.main import create_app
from backend.models.agent_tools import AgentPlan
from backend.services.agent_planner_service import AgentPlannerService
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec
from backend.services.product_agent_service import ProductAgentService


READING = {
    "source_text": "Gaussian processes provide a statistical anchor.",
    "translated_text": "高斯过程提供统计锚点。",
    "source_language": "en",
    "target_language": "zh-CN",
    "resource_url": "file:///paper.pdf",
    "resource_title": "Control paper",
    "section_heading": "3.4 Local refinement",
    "context_before": "Before",
    "context_after": "After",
    "source_kind": "pdf_uia",
}

COMPUTE_TOOL = AgentToolSpec(
    name="explain_selection",
    title="Explain selection",
    description="Explain the selected passage.",
    category="reading",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)
WRITE_TOOL = AgentToolSpec(
    name="save_research_note",
    title="Save research note",
    description="Persist the reading evidence.",
    category="research",
    effect="write",
    requires_reading_context=True,
    requires_confirmation=True,
    input_schema={"user_note": {"type": "string"}},
)


class FakePlanner:
    def __init__(self, plan: AgentPlan) -> None:
        self.result = plan
        self.calls = []

    def plan(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeRegistry:
    def __init__(self) -> None:
        self.tools = {tool.name: tool for tool in (COMPUTE_TOOL, WRITE_TOOL)}
        self.executions = []

    def list_tools(self):
        return tuple(self.tools.values())

    def get_tool(self, name: str):
        return self.tools.get(name)

    def execute(self, name: str, **payload):
        self.executions.append((name, payload))
        spec = self.tools[name]
        return AgentToolExecutionResult(
            tool_name=name,
            output_text="tool observation" if spec.effect != "write" else "Saved research note: Control paper",
            effect=spec.effect,
            provider="stub-tool",
            model="stub-model",
            request_id=payload.get("request_id", 0),
            data={"note_id": "note-1"} if spec.effect == "write" else {"evidence": "grounded"},
        )


class FakeChatService:
    def __init__(self) -> None:
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text="final synthesized answer",
            provider="stub-ai",
            model="stub-model",
            request_id=kwargs.get("request_id", 0),
        )


def run_payload(**overrides):
    return {
        **READING,
        "session_id": "agent-session-1",
        "user_message": "Explain this passage.",
        "style": "academic",
        "conversation_id": "conversation-1",
        "confirmed_write_tools": [],
        "request_id": 17,
        **overrides,
    }


def test_product_agent_answers_directly_without_forcing_a_tool() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        planner=FakePlanner(AgentPlan(action="answer", user_visible_reason="No tool is needed.")),
    )

    result = service.run(**run_payload(user_message="What is Bayesian optimization?"))

    assert result.status == "completed"
    assert result.output_text == "final synthesized answer"
    assert registry.executions == []
    assert chat.calls[0].get("tool_context") is None


def test_product_agent_executes_compute_tool_then_synthesizes_observation() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        planner=FakePlanner(
            AgentPlan(
                action="tool",
                tool_name="explain_selection",
                user_visible_reason="The reading tool can ground the explanation.",
            )
        ),
    )

    result = service.run(**run_payload())

    assert result.status == "completed"
    assert result.tool_result and result.tool_result.tool_name == "explain_selection"
    assert registry.executions[0][0] == "explain_selection"
    assert chat.calls[0]["tool_name"] == "explain_selection"
    assert '"evidence": "grounded"' in chat.calls[0]["tool_context"]


def test_enabled_tools_filter_the_route_catalog() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    planner = FakePlanner(AgentPlan(action="answer", user_visible_reason="Answer directly."))
    service = ProductAgentService(registry=registry, chat_service=chat, planner=planner)

    service.resolve_route(**run_payload(enabled_tools=["explain_selection"]))

    assert [tool.name for tool in planner.calls[0]["tools"]] == ["explain_selection"]


def test_enabled_tools_are_hard_execution_boundary() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    planner = FakePlanner(
        AgentPlan(
            action="tool",
            tool_name="save_research_note",
            user_visible_reason="The user asked to save this selection.",
        )
    )
    service = ProductAgentService(registry=registry, chat_service=chat, planner=planner)

    with pytest.raises(AgentToolError, match="outside the enabled tool scope"):
        service.run(**run_payload(enabled_tools=["explain_selection"]))
    assert registry.executions == []


def test_product_agent_stops_before_unconfirmed_write_tool() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    plan = AgentPlan(
        action="tool",
        tool_name="save_research_note",
        user_visible_reason="The user asked to save this selection.",
        arguments={"user_note": "Keep this argument."},
    )
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        planner=FakePlanner(plan),
    )

    result = service.run(**run_payload(user_message="Save this as a research note."))

    assert result.status == "confirmation_required"
    assert result.plan.tool_name == "save_research_note"
    assert registry.executions == []
    assert chat.calls == []


def test_product_agent_executes_confirmed_write_without_second_llm_call() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    plan = AgentPlan(
        action="tool",
        tool_name="save_research_note",
        user_visible_reason="The user confirmed the save action.",
        arguments={"user_note": "Keep this argument."},
    )
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        planner=FakePlanner(plan),
    )

    result = service.run(
        **run_payload(
            user_message="Save this as a research note.",
            confirmed_write_tools=["save_research_note"],
        )
    )

    assert result.status == "completed"
    assert result.output_text.startswith("Saved research note")
    assert registry.executions[0][1]["user_note"] == "Keep this argument."
    assert chat.calls == []


class FakeCompletionClient:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


class FakeTextService:
    provider_name = "stub-ai"
    model = "stub-model"

    def __init__(self, output: str) -> None:
        self.provider = SimpleNamespace(client=FakeCompletionClient(output))

    def close(self) -> None:
        return None


def test_agent_planner_accepts_only_registered_structured_plan() -> None:
    text_service = FakeTextService(
        '{"action":"tool","tool_name":"explain_selection","user_visible_reason":"Use grounded reading evidence.","arguments":{}}'
    )
    planner = AgentPlannerService(text_service=text_service)

    plan = planner.plan(tools=(COMPUTE_TOOL,), user_message="Explain it", **READING)

    assert plan.tool_name == "explain_selection"
    call = text_service.provider.client.calls[0]
    assert call["temperature"] == 0.0
    assert "registered_tools" in call["user_prompt"]


def test_agent_planner_rejects_hallucinated_tool_name() -> None:
    planner = AgentPlannerService(
        text_service=FakeTextService(
            '{"action":"tool","tool_name":"delete_everything","user_visible_reason":"No.","arguments":{}}'
        )
    )

    with pytest.raises(AIResponseError, match="unregistered tool"):
        planner.plan(tools=(COMPUTE_TOOL,), user_message="Do something", **READING)


def test_agent_run_http_contract_surfaces_confirmation_without_side_effect() -> None:
    registry = FakeRegistry()
    chat = FakeChatService()
    service = ProductAgentService(
        registry=registry,
        chat_service=chat,
        planner=FakePlanner(
            AgentPlan(
                action="tool",
                tool_name="save_research_note",
                user_visible_reason="Saving changes persistent research state.",
            )
        ),
    )
    app = create_app()
    app.dependency_overrides[get_product_agent_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/agent/run",
        json=run_payload(user_message="Save this passage."),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation_required"
    assert body["plan"]["tool_name"] == "save_research_note"
    assert body["tool_result"] is None
    assert registry.executions == []
