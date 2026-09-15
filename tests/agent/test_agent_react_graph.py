from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.events import AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_react import AgentReActDecision
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec


TOOL = AgentToolSpec(
    name="inspect_reading_context",
    title="Inspect context",
    description="Inspect the current reading context.",
    category="reading",
    effect="read",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)


class ComplexService:
    def __init__(self) -> None:
        self.executions = 0
        self.synthesis_calls = 0

    def list_tools(self):
        return (TOOL,)

    def resolve_route(self, *, control=None, **_payload):
        return (
            AgentRouteDecision(
                kind="complex",
                source="semantic_router",
                intent="complex",
                user_visible_reason="Use bounded ReAct.",
            ),
            {
                "duration_ms": 1,
                "provider": "fake-router",
                "model": "fake-router-model",
                "prompt_id": "router@test",
                "llm_called": True,
            },
        )

    def run(self, *, event_sink=None, control=None, **payload):
        route = AgentRouteDecision.model_validate(payload["_resolved_route"])
        self.executions += 1
        result = AgentToolExecutionResult(
            tool_name=route.tool_name,
            output_text="compact observation",
            effect="read",
            provider="fake-tool",
            model="fake-tool-model",
            request_id=payload.get("request_id", 0),
            data={},
        )
        if event_sink is not None:
            event_sink(
                "tool_call",
                {
                    "name": route.tool_name,
                    "arguments": dict(route.arguments),
                    "effect": "read",
                    "request_id": result.request_id,
                },
            )
            event_sink(
                "tool_result",
                {
                    "tool_name": route.tool_name,
                    "output_text": result.output_text,
                    "effect": "read",
                    "provider": result.provider,
                    "model": result.model,
                    "request_id": result.request_id,
                    "data": {},
                },
            )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="tool",
                tool_name=route.tool_name,
                user_visible_reason="Inspect context.",
                arguments=dict(route.arguments),
            ),
            output_text=result.output_text,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            tool_result=result,
            route=route,
        )

    def synthesize_multi_step(self, *, tool_results, event_sink=None, **payload):
        self.synthesis_calls += 1
        assert tool_results
        if event_sink is not None:
            event_sink(
                "synthesis_ready",
                {
                    "provider": "fake-synthesis",
                    "model": "fake-synthesis-model",
                    "request_id": payload.get("request_id", 0),
                },
            )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(action="answer", user_visible_reason="Synthesize observations."),
            output_text="bounded fallback answer",
            provider="fake-synthesis",
            model="fake-synthesis-model",
            request_id=payload.get("request_id", 0),
            route=AgentRouteDecision(
                kind="complex",
                source="planner",
                intent="complex",
                user_visible_reason="Bounded ReAct synthesis.",
            ),
        )


class ImmediateFinalDecision:
    provider_name = "fake-react"
    model = "fake-react-model"
    prompt_id = "react@test"

    def decide(self, *, iteration, **_kwargs):
        assert iteration == 1
        return AgentReActDecision(
            iteration=1,
            kind="final",
            action_summary="Answer directly.",
            final_answer="No tool is needed for this complex-looking request.",
        )


class AlwaysToolDecision:
    provider_name = "fake-react"
    model = "fake-react-model"
    prompt_id = "react@test"

    def decide(self, *, iteration, **_kwargs):
        return AgentReActDecision(
            iteration=iteration,
            kind="tool",
            tool_name="inspect_reading_context",
            action_summary="Inspect one more observable fact.",
        )


def _state() -> AgentState:
    return AgentState(
        session_id="react-boundary",
        user_input="Analyze this context carefully.",
        selected_text="Gaussian process uncertainty.",
        browser_context={"request_id": 77, "source_kind": "pdf"},
    )


def test_complex_route_can_finish_without_forcing_a_tool() -> None:
    service = ComplexService()
    runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=ImmediateFinalDecision(),
        )
    )

    result = runtime.execute(_state())

    assert service.executions == 0
    assert service.synthesis_calls == 0
    assert result.react.status == "completed"
    assert result.response["output_text"].startswith("No tool is needed")
    decision_event = next(
        event for event in runtime.events if event.event_type == AgentEventType.DECISION_READY
    )
    assert decision_event.payload["kind"] == "final"
    assert "final_answer" not in decision_event.payload


def test_react_iteration_limit_synthesizes_existing_observation_and_stops() -> None:
    service = ComplexService()
    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            max_react_iterations=1,
            max_tool_calls=4,
        )
    )
    runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=AlwaysToolDecision(),
        )
    )

    result = runtime.execute(_state(), control=control)

    assert service.executions == 1
    assert service.synthesis_calls == 1
    assert result.react.status == "limit_reached"
    assert len(result.react.decisions) == 1
    assert len(result.react.observations) == 1
    assert result.response["output_text"] == "bounded fallback answer"
    assert AgentEventType.REACT_LIMIT_REACHED in {
        event.event_type for event in runtime.events
    }
    assert runtime.events[-1].event_type == AgentEventType.AGENT_END


def test_react_repeated_action_guard_stops_before_second_tool_execution() -> None:
    service = ComplexService()
    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            max_react_iterations=4,
            max_tool_calls=4,
        )
    )
    runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=AlwaysToolDecision(),
        )
    )

    result = runtime.execute(_state(), control=control)

    assert service.executions == 1
    assert service.synthesis_calls == 1
    assert result.react.status == "limit_reached"
    assert len(result.react.decisions) == 2
    assert len(result.react.observations) == 1
    assert result.response["output_text"] == "bounded fallback answer"

    limit_event = next(
        event
        for event in runtime.events
        if event.event_type == AgentEventType.REACT_LIMIT_REACHED
    )
    assert limit_event.payload["reason"] == "repeated_action_detected"
    assert limit_event.payload["tool_call_count"] == 1

    decision_events = [
        event
        for event in runtime.events
        if event.event_type == AgentEventType.DECISION_READY
    ]
    assert len(decision_events) == 2
    assert decision_events[0].payload["action_fingerprint"]
    assert (
        decision_events[0].payload["action_fingerprint"]
        == decision_events[1].payload["action_fingerprint"]
    )
