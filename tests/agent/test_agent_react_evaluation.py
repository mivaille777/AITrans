from __future__ import annotations

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.state import AgentState
from backend.evaluation.agent_evaluator import (
    AgentEvaluationExpectation,
    derive_agent_trajectory_metrics,
    evaluate_agent_run,
)
from backend.services.agent_trace_store_service import (
    AgentTraceStoreService,
    StoredAgentEvent,
    StoredAgentRun,
)


def stored_run(*, status: str = "completed", tool_name: str = "explain_selection") -> StoredAgentRun:
    return StoredAgentRun(
        run_id="run-react-eval",
        trace_id="trace-react-eval",
        session_id="session",
        created_at="2026-08-27T00:00:00+00:00",
        status=status,
        intent="complex",
        ui_mode="assistant",
        tool_name=tool_name,
        provider="stub",
        model="stub-model",
        total_duration_ms=120,
        planning_duration_ms=0,
        tool_duration_ms=30,
        synthesis_duration_ms=20,
        retry_count=0,
        failure_count=0,
        timeout_count=0,
        fallback_reason="",
        event_count=10,
    )


def event(sequence: int, event_type: str, **payload: object) -> StoredAgentEvent:
    return StoredAgentEvent(
        sequence=sequence,
        event_type=event_type,
        timestamp=f"2026-08-27T00:00:{sequence:02d}+00:00",
        elapsed_ms=sequence * 10,
        payload=dict(payload),
    )


def successful_react_events() -> tuple[StoredAgentEvent, ...]:
    return (
        event(0, "react_started", max_iterations=6, max_tool_calls=4),
        event(
            1,
            "decision_ready",
            iteration=1,
            kind="tool",
            tool_name="knowledge_search",
            action_fingerprint="fp-search",
        ),
        event(2, "tool_call", name="knowledge_search", effect="read"),
        event(3, "rag_evidence_selected", final_count=3),
        event(
            4,
            "observation_ready",
            iteration=1,
            tool_name="knowledge_search",
            success=True,
            evidence_count=3,
            citation_count=2,
        ),
        event(
            5,
            "decision_ready",
            iteration=2,
            kind="tool",
            tool_name="explain_selection",
            action_fingerprint="fp-explain",
        ),
        event(6, "tool_call", name="explain_selection", effect="compute"),
        event(
            7,
            "observation_ready",
            iteration=2,
            tool_name="explain_selection",
            success=True,
            evidence_count=3,
            citation_count=2,
        ),
        event(8, "decision_ready", iteration=3, kind="final"),
        event(9, "synthesis_ready", grounded=True),
    )


def test_trajectory_evaluator_scores_successful_react_path() -> None:
    run = stored_run()
    events = successful_react_events()

    metrics = derive_agent_trajectory_metrics(events, run_status=run.status)

    assert metrics.react_started is True
    assert metrics.react_iteration_count == 3
    assert metrics.decision_count == 3
    assert metrics.tool_call_count == 2
    assert metrics.observation_count == 2
    assert metrics.tool_sequence == ("knowledge_search", "explain_selection")
    assert metrics.redundant_action_count == 0
    assert metrics.react_limit_reached is False
    assert metrics.grounded is True
    assert metrics.evidence_count == 3
    assert metrics.citation_count == 2

    result = evaluate_agent_run(
        run,
        AgentEvaluationExpectation(
            case_id="react-grounded",
            expected_intent="complex",
            expected_tool_name="explain_selection",
            expected_tool_sequence=("knowledge_search", "explain_selection"),
            expect_react=True,
            max_react_iterations=3,
            max_tool_calls=2,
            max_redundant_actions=0,
            require_no_react_limit=True,
            require_grounded_response=True,
        ),
        events=events,
    )

    assert result.passed is True
    assert result.score == 1.0
    assert result.failures == ()


def test_trajectory_evaluator_detects_duplicate_action_and_limit() -> None:
    run = stored_run(tool_name="knowledge_search")
    events = (
        event(0, "react_started"),
        event(
            1,
            "decision_ready",
            iteration=1,
            kind="tool",
            tool_name="knowledge_search",
            action_fingerprint="same-fingerprint",
        ),
        event(2, "tool_call", name="knowledge_search", effect="read"),
        event(3, "observation_ready", iteration=1, tool_name="knowledge_search"),
        event(
            4,
            "decision_ready",
            iteration=2,
            kind="tool",
            tool_name="knowledge_search",
            action_fingerprint="same-fingerprint",
        ),
        event(
            5,
            "react_limit_reached",
            iteration=2,
            tool_call_count=1,
            reason="repeated_action_detected",
        ),
    )

    result = evaluate_agent_run(
        run,
        AgentEvaluationExpectation(
            case_id="no-loop",
            expect_react=True,
            max_redundant_actions=0,
            require_no_react_limit=True,
        ),
        events=events,
    )

    assert result.passed is False
    assert result.trajectory.redundant_action_count == 1
    assert result.trajectory.react_limit_reason == "repeated_action_detected"
    assert result.redundancy_pass is False
    assert result.react_limit_pass is False
    assert any("redundant_actions" in failure for failure in result.failures)


def test_confirmation_guard_detects_write_before_confirmation_boundary() -> None:
    run = stored_run(status="confirmation_required", tool_name="save_research_note")
    safe_events = (
        event(
            0,
            "tool_call",
            name="save_research_note",
            effect="write",
            requires_confirmation=True,
        ),
    )
    expectation = AgentEvaluationExpectation(
        case_id="write-confirmation",
        expected_status="confirmation_required",
        require_confirmation_guard=True,
    )

    safe = evaluate_agent_run(run, expectation, events=safe_events)
    assert safe.passed is True
    assert safe.trajectory.confirmation_required_action_count == 1
    assert safe.trajectory.write_result_count == 0

    unsafe_events = safe_events + (
        event(1, "tool_result", tool_name="save_research_note", effect="write"),
    )
    unsafe = evaluate_agent_run(run, expectation, events=unsafe_events)
    assert unsafe.passed is False
    assert unsafe.confirmation_pass is False
    assert "write confirmation guard was bypassed" in unsafe.failures


def test_trace_store_persists_react_metrics_without_private_decision_text(tmp_path) -> None:
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    state = AgentState(session_id="s1", intent="complex")
    events = (
        AgentEvent(
            event_type=AgentEventType.REACT_STARTED,
            run_id=state.run_id,
            trace_id=state.trace_id,
            payload={"max_iterations": 6, "max_tool_calls": 4},
        ),
        AgentEvent(
            event_type=AgentEventType.DECISION_READY,
            run_id=state.run_id,
            trace_id=state.trace_id,
            payload={
                "iteration": 1,
                "kind": "tool",
                "tool_name": "knowledge_search",
                "argument_keys": ["query"],
                "action_fingerprint": "opaque-run-local-hash",
                "action_summary": "PRIVATE DECISION SUMMARY",
                "arguments": {"query": "PRIVATE QUERY"},
            },
        ),
        AgentEvent(
            event_type=AgentEventType.REACT_LIMIT_REACHED,
            run_id=state.run_id,
            trace_id=state.trace_id,
            payload={
                "iteration": 1,
                "tool_call_count": 0,
                "reason": "repeated_action_detected",
            },
        ),
    )

    store.record(state, events)
    persisted = store.list_events(state.run_id)
    serialized = repr(persisted)

    assert persisted[1].payload["action_fingerprint"] == "opaque-run-local-hash"
    assert persisted[2].payload["reason"] == "repeated_action_detected"
    assert "PRIVATE DECISION SUMMARY" not in serialized
    assert "PRIVATE QUERY" not in serialized
