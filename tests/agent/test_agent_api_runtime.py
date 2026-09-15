from __future__ import annotations

from time import sleep

from fastapi.testclient import TestClient

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.state import AgentState
from backend.api.agent import run_product_agent, run_product_agent_trace
from backend.api.agent_dependencies import get_agent_runtime
from backend.main import create_app
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.agent_tools import AgentRunRequest


class FakeRuntime:
    def __init__(self, *, confirmation_required: bool = False) -> None:
        self.confirmation_required = confirmation_required
        self.received: AgentState | None = None
        self.events: list[AgentEvent] = []

    def execute(self, state: AgentState, *, event_sink=None, control=None) -> AgentState:
        self.received = state
        self.events = []

        def emit(event_type: AgentEventType, payload: dict) -> None:
            event = AgentEvent(
                event_type=event_type,
                payload=payload,
                run_id=state.run_id,
                trace_id=state.trace_id,
                elapsed_ms=len(self.events) * 5,
            )
            self.events.append(event)
            if event_sink is not None:
                event_sink(event)

        emit(AgentEventType.AGENT_START, {"session_id": state.session_id})
        emit(AgentEventType.CONTEXT_READY, {"source_text": state.selected_text})

        if self.confirmation_required:
            state.planned_action = {
                "action": "tool",
                "tool_name": "save_research_note",
                "user_visible_reason": "Save the selected passage as a note.",
                "arguments": {"user_note": "important"},
            }
            state.intent = "save_research_note"
            state.tool_calls.append(
                {
                    "name": "save_research_note",
                    "arguments": {"user_note": "important"},
                }
            )
            state.response = {
                "status": "confirmation_required",
                "output_text": "",
                "provider": "",
                "model": "",
                "request_id": 12,
            }
            state.ui_mode = "note"
            emit(AgentEventType.PLAN_READY, dict(state.planned_action))
            emit(AgentEventType.TOOL_CALL, {"name": "save_research_note"})
            emit(
                AgentEventType.AGENT_END,
                {
                    "intent": state.intent,
                    "status": "confirmation_required",
                    "ui_mode": state.ui_mode,
                },
            )
            return state

        state.planned_action = {
            "action": "tool",
            "tool_name": "translate_selection",
            "user_visible_reason": "Translate the selected passage.",
            "arguments": {"target_language": "zh-CN"},
        }
        state.intent = "translate_selection"
        state.tool_calls.append(
            {
                "name": "translate_selection",
                "arguments": {"target_language": "zh-CN"},
            }
        )
        state.tool_results.append(
            {
                "tool_name": "translate_selection",
                "output_text": "贝叶斯优化",
                "effect": "compute",
                "provider": "fake",
                "model": "",
                "request_id": 12,
                "data": {
                    "source_language": "en",
                    "target_language": "zh-CN",
                },
            }
        )
        state.response = {
            "status": "completed",
            "output_text": "贝叶斯优化",
            "provider": "fake",
            "model": "",
            "request_id": 12,
        }
        state.ui_mode = "translation"
        emit(AgentEventType.PLAN_READY, dict(state.planned_action))
        emit(AgentEventType.TOOL_CALL, {"name": "translate_selection"})
        emit(AgentEventType.TOOL_RESULT, {"tool_name": "translate_selection"})
        emit(AgentEventType.SYNTHESIS_READY, {"provider": "fake", "duration_ms": 2})
        emit(
            AgentEventType.AGENT_END,
            {
                "intent": state.intent,
                "status": "completed",
                "ui_mode": state.ui_mode,
                "total_duration_ms": 30,
            },
        )
        return state


class CancellableRuntime:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def execute(self, state: AgentState, *, event_sink=None, control=None) -> AgentState:
        assert control is not None
        event = AgentEvent(
            event_type=AgentEventType.AGENT_START,
            payload={"session_id": state.session_id},
            run_id=state.run_id,
            trace_id=state.trace_id,
        )
        self.events = [event]
        if event_sink is not None:
            event_sink(event)
        while True:
            sleep(0.005)
            control.checkpoint("cancellable_test")


class EvidenceRuntime(FakeRuntime):
    def execute(self, state: AgentState, *, event_sink=None, control=None) -> AgentState:
        state = super().execute(state, event_sink=event_sink, control=control)
        state.evidence = [
            AgentEvidenceItem(
                evidence_id="evidence:chunk-1",
                source_type="knowledge",
                source_id="document-1",
                title="Control Paper",
                resource_url="file:///C:/papers/control.pdf",
                location="Page 3 · Section Method",
                excerpt="The controller uses bounded evidence.",
                score=0.91,
            )
        ]
        state.citations = [
            AgentCitationRef(
                citation_id="citation-1",
                evidence_ids=["evidence:chunk-1"],
                label="[1]",
            )
        ]
        state.response["output_text"] = "Grounded response [1]"
        return state


def _request() -> AgentRunRequest:
    return AgentRunRequest(
        session_id="session-12",
        trace_id="trace-api-12",
        user_message="Translate this selection",
        source_text="Bayesian optimization",
        source_language="en",
        target_language="zh-CN",
        resource_title="Paper",
        section_heading="Method",
        context_before="We tune the controller with",
        context_after="under bounded evaluations.",
        source_kind="browser_selection",
        style="academic",
        conversation_id="conversation-7",
        request_id=12,
    )


def test_agent_run_api_preserves_existing_response_contract_through_runtime() -> None:
    runtime = FakeRuntime()

    response = run_product_agent(_request(), runtime)

    assert runtime.received is not None
    assert runtime.received.session_id == "session-12"
    assert runtime.received.trace_id == "trace-api-12"
    assert runtime.received.user_input == "Translate this selection"
    assert runtime.received.selected_text == "Bayesian optimization"
    assert runtime.received.browser_context["resource_title"] == "Paper"
    assert runtime.received.browser_context["conversation_id"] == "conversation-7"
    assert runtime.received.browser_context["request_id"] == 12

    assert response.status == "completed"
    assert response.plan.tool_name == "translate_selection"
    assert response.output_text == "贝叶斯优化"
    assert response.provider == "fake"
    assert response.request_id == 12
    assert response.tool_result is not None
    assert response.tool_result.tool_name == "translate_selection"
    assert response.tool_result.data["target_language"] == "zh-CN"


def test_agent_run_api_preserves_write_confirmation_gate() -> None:
    runtime = FakeRuntime(confirmation_required=True)

    response = run_product_agent(_request(), runtime)

    assert response.status == "confirmation_required"
    assert response.plan.tool_name == "save_research_note"
    assert response.tool_result is None
    assert runtime.received is not None
    assert runtime.received.tool_results == []


def test_agent_trace_response_includes_correlation_and_timing_metadata() -> None:
    runtime = FakeRuntime()

    response = run_product_agent_trace(_request(), runtime)

    assert response.run_id.startswith("run-")
    assert response.trace_id == "trace-api-12"
    assert response.session_id == "session-12"
    assert response.ui_mode == "translation"
    assert response.total_duration_ms == 30
    assert response.run.output_text == "贝叶斯优化"
    assert [event.sequence for event in response.events] == list(range(7))
    assert [event.event_type for event in response.events] == [
        "agent_start",
        "context_ready",
        "plan_ready",
        "tool_call",
        "tool_result",
        "synthesis_ready",
        "agent_end",
    ]
    assert all(event.run_id == response.run_id for event in response.events)
    assert all(event.trace_id == "trace-api-12" for event in response.events)


def test_agent_response_exposes_program_verified_evidence_and_citations() -> None:
    response = run_product_agent_trace(_request(), EvidenceRuntime())

    assert response.run.output_text == "Grounded response [1]"
    assert response.run.citations[0].label == "[1]"
    assert response.run.citations[0].evidence_ids == ["evidence:chunk-1"]
    assert response.run.evidence[0].resource_url == "file:///C:/papers/control.pdf"
    assert response.run.evidence[0].location == "Page 3 · Section Method"


def test_agent_trace_confirmation_has_no_tool_result_event() -> None:
    runtime = FakeRuntime(confirmation_required=True)

    response = run_product_agent_trace(_request(), runtime)

    assert response.run.status == "confirmation_required"
    assert response.run.plan.tool_name == "save_research_note"
    assert response.run.tool_result is None
    assert "tool_result" not in {event.event_type for event in response.events}


def test_agent_trace_http_endpoint_is_additive_to_existing_run_api() -> None:
    runtime = FakeRuntime()
    app = create_app()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    client = TestClient(app)

    response = client.post("/api/agent/run/trace", json=_request().model_dump())

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"].startswith("run-")
    assert body["trace_id"] == "trace-api-12"
    assert body["run"]["status"] == "completed"
    assert body["run"]["tool_result"]["tool_name"] == "translate_selection"
    assert body["events"][0]["event_type"] == "agent_start"
    assert body["events"][-1]["event_type"] == "agent_end"


def test_agent_websocket_streams_activity_before_terminal_trace() -> None:
    runtime = FakeRuntime()
    app = create_app()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    client = TestClient(app)

    with client.websocket_connect("/api/agent/stream") as websocket:
        websocket.send_json({"type": "start", "request": _request().model_dump()})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["request_id"] == 12
        assert accepted["session_id"] == "session-12"
        assert accepted["run_id"].startswith("run-")
        assert accepted["trace_id"] == "trace-api-12"

        activity_types = []
        terminal = None
        while terminal is None:
            event = websocket.receive_json()
            if event["type"] == "activity":
                activity_types.append(event["event"]["event_type"])
            else:
                terminal = event

    assert activity_types == [
        "agent_start",
        "context_ready",
        "plan_ready",
        "tool_call",
        "tool_result",
        "synthesis_ready",
        "agent_end",
    ]
    assert terminal is not None
    assert terminal["type"] == "done"
    assert terminal["trace_id"] == "trace-api-12"
    assert terminal["trace"]["run"]["output_text"] == "贝叶斯优化"


def test_agent_websocket_confirmation_never_streams_tool_result() -> None:
    runtime = FakeRuntime(confirmation_required=True)
    app = create_app()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    client = TestClient(app)

    with client.websocket_connect("/api/agent/stream") as websocket:
        websocket.send_json({"type": "start", "request": _request().model_dump()})
        assert websocket.receive_json()["type"] == "accepted"
        activity_types = []
        while True:
            event = websocket.receive_json()
            if event["type"] == "activity":
                activity_types.append(event["event"]["event_type"])
                continue
            assert event["type"] == "done"
            assert event["trace"]["run"]["status"] == "confirmation_required"
            break

    assert "tool_call" in activity_types
    assert "tool_result" not in activity_types


def test_agent_websocket_cancel_is_request_then_terminal_acknowledgement() -> None:
    runtime = CancellableRuntime()
    app = create_app()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    client = TestClient(app)

    with client.websocket_connect("/api/agent/stream") as websocket:
        websocket.send_json({"type": "start", "request": _request().model_dump()})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        websocket.send_json({"type": "cancel", "request_id": 12})

        event_types = []
        while True:
            event = websocket.receive_json()
            event_types.append(event["type"])
            if event["type"] == "cancelled":
                assert event["trace_id"] == "trace-api-12"
                break

    assert "cancel_requested" in event_types
    assert event_types[-1] == "cancelled"


class FakeProductAgentService:
    pass


class FakeReadingSelectionResolver:
    pass


def test_agent_runtime_dependency_is_request_scoped() -> None:
    service = FakeProductAgentService()
    resolver = FakeReadingSelectionResolver()

    first = get_agent_runtime(service, resolver)
    second = get_agent_runtime(service, resolver)

    assert first is not second
    assert first.events == []
    assert second.events == []
