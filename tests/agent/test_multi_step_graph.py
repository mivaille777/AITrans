from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.events import AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_react import AgentReActDecision
from backend.models.agent_runtime import (
    AgentPlanContext,
    AgentPlanStep,
    AgentRouteDecision,
)
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec


TRANSLATE_TOOL = AgentToolSpec(
    name="translate_selection",
    title="Translate",
    description="Translate selection",
    category="translation",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={"target_language": {"type": "string", "maxLength": 64}},
)
EXPLAIN_TOOL = AgentToolSpec(
    name="explain_selection",
    title="Explain",
    description="Explain selection",
    category="reading",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)


class FakeComplexProductAgentService:
    def __init__(self) -> None:
        self.route_calls = 0
        self.step_tools: list[str] = []
        self.synthesis_calls = 0

    def list_tools(self):
        return (TRANSLATE_TOOL, EXPLAIN_TOOL)

    def resolve_route(self, *, control=None, **_payload):
        self.route_calls += 1
        return (
            AgentRouteDecision(
                kind="complex",
                source="semantic_router",
                intent="complex",
                user_visible_reason="This request combines multiple reading actions.",
            ),
            {
                "duration_ms": 1,
                "provider": "",
                "model": "",
                "prompt_id": "",
                "llm_called": False,
            },
        )

    def run(self, *, event_sink=None, control=None, **payload):
        route = AgentRouteDecision.model_validate(payload["_resolved_route"])
        tool_name = route.tool_name
        self.step_tools.append(tool_name)
        if event_sink is not None:
            event_sink(
                "tool_call",
                {
                    "name": tool_name,
                    "arguments": dict(route.arguments),
                    "effect": "compute",
                    "request_id": payload.get("request_id", 0),
                },
            )
        result = AgentToolExecutionResult(
            tool_name=tool_name,
            output_text=f"result:{tool_name}",
            effect="compute",
            provider="fake-tool",
            model="fake-tool-model",
            request_id=payload.get("request_id", 0),
            data={"step_tool": tool_name},
        )
        if event_sink is not None:
            event_sink(
                "tool_result",
                {
                    "tool_name": tool_name,
                    "output_text": result.output_text,
                    "effect": "compute",
                    "provider": result.provider,
                    "model": result.model,
                    "request_id": result.request_id,
                    "data": result.data,
                },
            )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="tool",
                tool_name=tool_name,
                user_visible_reason=f"Execute {tool_name}.",
                arguments=dict(route.arguments),
            ),
            output_text=result.output_text,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            tool_result=result,
            route=route,
        )

    def synthesize_multi_step(
        self,
        *,
        tool_results,
        event_sink=None,
        control=None,
        **payload,
    ):
        self.synthesis_calls += 1
        assert [item["tool_name"] for item in tool_results] == [
            "translate_selection",
            "explain_selection",
        ]
        if event_sink is not None:
            event_sink(
                "synthesis_ready",
                {
                    "provider": "fake-chat",
                    "model": "fake-chat-model",
                    "request_id": payload.get("request_id", 0),
                    "duration_ms": 3,
                },
            )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="answer",
                user_visible_reason="Synthesize completed observations.",
            ),
            output_text="final ReAct answer",
            provider="fake-chat",
            model="fake-chat-model",
            request_id=payload.get("request_id", 0),
            tool_result=None,
            route=AgentRouteDecision(
                kind="complex",
                source="planner",
                intent="complex",
                user_visible_reason="Completed bounded ReAct loop.",
            ),
        )


class FakeReActDecisionService:
    provider_name = "fake-react"
    model = "fake-react-model"
    prompt_id = "agent.react_decision@test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def decide(self, *, iteration, observations=(), **kwargs):
        self.calls.append(
            {
                "iteration": iteration,
                "observation_count": len(observations),
                "tools": kwargs.get("tools", ()),
            }
        )
        if iteration == 1:
            return AgentReActDecision(
                iteration=1,
                kind="tool",
                tool_name="translate_selection",
                arguments={"target_language": "zh-CN"},
                action_summary="Translate the selection.",
            )
        if iteration == 2:
            assert len(observations) == 1
            return AgentReActDecision(
                iteration=2,
                kind="tool",
                tool_name="explain_selection",
                action_summary="Explain the translated concept.",
            )
        assert len(observations) == 2
        return AgentReActDecision(
            iteration=3,
            kind="final",
            action_summary="Answer with the completed observations.",
            final_answer="decision-layer answer",
        )

    def close(self) -> None:
        pass


def _state() -> AgentState:
    return AgentState(
        session_id="react-session",
        user_input="先翻译，然后解释一下",
        selected_text="Gaussian processes model uncertainty.",
        browser_context={
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_title": "Paper",
            "source_kind": "pdf",
            "request_id": 41,
        },
    )


def test_reading_agent_graph_executes_bounded_react_loop_and_synthesizes_once() -> None:
    service = FakeComplexProductAgentService()
    decisions = FakeReActDecisionService()
    runtime = AgentRuntime(
        context_provider=lambda state: dict(state.browser_context),
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=decisions,
        ),
    )

    result = runtime.execute(_state())

    assert service.route_calls == 1
    assert service.step_tools == ["translate_selection", "explain_selection"]
    assert service.synthesis_calls == 1
    assert [call["observation_count"] for call in decisions.calls] == [0, 1, 2]
    assert result.route.kind == "complex"
    assert result.react.status == "completed"
    assert [item.kind for item in result.react.decisions] == ["tool", "tool", "final"]
    assert [item.tool_name for item in result.react.observations] == [
        "translate_selection",
        "explain_selection",
    ]
    assert [item["step_id"] for item in result.tool_results] == ["react-1", "react-2"]
    assert result.response["status"] == "completed"
    assert result.response["output_text"] == "final ReAct answer"
    assert [event.event_type for event in runtime.events] == [
        AgentEventType.AGENT_START,
        AgentEventType.CONTEXT_READY,
        AgentEventType.PLAN_READY,
        AgentEventType.REACT_STARTED,
        AgentEventType.DECISION_READY,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.OBSERVATION_READY,
        AgentEventType.DECISION_READY,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.OBSERVATION_READY,
        AgentEventType.DECISION_READY,
        AgentEventType.SYNTHESIS_READY,
        AgentEventType.AGENT_END,
    ]


def test_multi_step_plan_survives_legacy_tool_state_synchronization() -> None:
    state = _state()
    state.apply_route(
        AgentRouteDecision(
            kind="complex",
            source="semantic_router",
            intent="complex",
        )
    )
    state.apply_multi_step_plan(
        AgentPlanContext(
            goal="Translate and explain.",
            mode="multi_step",
            steps=[
                AgentPlanStep(step_id="step-1", tool_name="translate_selection"),
                AgentPlanStep(
                    step_id="step-2",
                    tool_name="explain_selection",
                    depends_on=["step-1"],
                ),
            ],
            current_step_id="step-1",
        )
    )

    state.record_tool_call({"name": "translate_selection", "step_id": "step-1"})
    state.record_tool_result(
        {
            "tool_name": "translate_selection",
            "output_text": "结果",
            "effect": "compute",
            "step_id": "step-1",
        }
    )

    assert state.route.kind == "complex"
    assert state.plan.mode == "multi_step"
    assert [step.tool_name for step in state.plan.steps] == [
        "translate_selection",
        "explain_selection",
    ]
