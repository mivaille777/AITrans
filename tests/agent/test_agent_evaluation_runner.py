from __future__ import annotations

from backend.evaluation.agent_evaluator import AgentEvaluationExpectation
from backend.evaluation.runner import evaluate_agent_batch
from backend.services.agent_trace_store_service import StoredAgentEvent, StoredAgentRun


def stored_run(*, run_id: str, intent: str, tool_name: str, status: str) -> StoredAgentRun:
    return StoredAgentRun(
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        session_id="session",
        created_at="2026-08-22T00:00:00+00:00",
        status=status,
        intent=intent,
        ui_mode="assistant",
        tool_name=tool_name,
        provider="stub",
        model="stub-model",
        total_duration_ms=100,
        planning_duration_ms=20,
        tool_duration_ms=30,
        synthesis_duration_ms=50,
        retry_count=0,
        failure_count=0,
        timeout_count=0,
        fallback_reason="",
        event_count=6,
    )


def stored_event(sequence: int, event_type: str, **payload: object) -> StoredAgentEvent:
    return StoredAgentEvent(
        sequence=sequence,
        event_type=event_type,
        timestamp=f"2026-08-27T00:00:{sequence:02d}+00:00",
        elapsed_ms=sequence * 10,
        payload=dict(payload),
    )


def test_agent_evaluation_batch_reports_pass_rate_and_missing_run() -> None:
    cases = (
        AgentEvaluationExpectation(
            case_id="translate",
            expected_intent="translate_selection",
            expected_tool_name="translate_selection",
        ),
        AgentEvaluationExpectation(
            case_id="missing",
            expected_intent="explain_selection",
            expected_tool_name="explain_selection",
        ),
    )
    runs = {
        "translate": stored_run(
            run_id="run-1",
            intent="translate_selection",
            tool_name="translate_selection",
            status="completed",
        )
    }

    result = evaluate_agent_batch(cases, resolve_run=lambda case: runs.get(case.case_id))

    assert result.total_cases == 2
    assert result.passed_cases == 1
    assert result.pass_rate == 0.5
    assert result.average_score == 0.5
    assert result.trajectory_case_count == 0
    assert result.average_knowledge_searches == 0.0
    assert result.results[1].passed is False
    assert "no persisted run" in result.results[1].failures[0]


def test_agent_evaluation_batch_aggregates_react_and_agentic_rag_metrics() -> None:
    cases = (
        AgentEvaluationExpectation(
            case_id="react-grounded",
            expected_intent="complex",
            expect_react=True,
            max_tool_calls=2,
            max_redundant_actions=0,
            require_no_react_limit=True,
            require_grounded_response=True,
        ),
        AgentEvaluationExpectation(
            case_id="react-limited",
            expected_intent="complex",
            expect_react=True,
        ),
    )
    runs = {
        "react-grounded": stored_run(
            run_id="run-grounded",
            intent="complex",
            tool_name="search_knowledge_base",
            status="completed",
        ),
        "react-limited": stored_run(
            run_id="run-limited",
            intent="complex",
            tool_name="search_knowledge_base",
            status="completed",
        ),
    }
    events = {
        "run-grounded": (
            stored_event(0, "react_started"),
            stored_event(
                1,
                "decision_ready",
                iteration=1,
                kind="tool",
                tool_name="search_knowledge_base",
                action_fingerprint="search-a",
            ),
            stored_event(2, "tool_call", name="search_knowledge_base", effect="read"),
            stored_event(
                3,
                "observation_ready",
                iteration=1,
                tool_name="search_knowledge_base",
                evidence_count=1,
                citation_count=1,
                query_fingerprint="query-a",
                novel_evidence_count=1,
                retrieval_fallback=False,
            ),
            stored_event(
                4,
                "decision_ready",
                iteration=2,
                kind="tool",
                tool_name="search_knowledge_base",
                action_fingerprint="search-b",
            ),
            stored_event(5, "tool_call", name="search_knowledge_base", effect="read"),
            stored_event(
                6,
                "observation_ready",
                iteration=2,
                tool_name="search_knowledge_base",
                evidence_count=2,
                citation_count=2,
                query_fingerprint="query-b",
                novel_evidence_count=1,
                retrieval_fallback=False,
            ),
            stored_event(7, "decision_ready", iteration=3, kind="final"),
            stored_event(8, "synthesis_ready", grounded=True),
        ),
        "run-limited": (
            stored_event(0, "react_started"),
            stored_event(
                1,
                "decision_ready",
                iteration=1,
                kind="tool",
                tool_name="search_knowledge_base",
                action_fingerprint="search-c",
            ),
            stored_event(2, "tool_call", name="search_knowledge_base", effect="read"),
            stored_event(
                3,
                "observation_ready",
                iteration=1,
                tool_name="search_knowledge_base",
                query_fingerprint="query-c",
                novel_evidence_count=0,
                retrieval_fallback=True,
            ),
            stored_event(
                4,
                "decision_ready",
                iteration=2,
                kind="tool",
                tool_name="search_knowledge_base",
                action_fingerprint="search-c",
            ),
            stored_event(
                5,
                "react_limit_reached",
                iteration=2,
                tool_call_count=1,
                knowledge_search_count=1,
                reason="repeated_action_detected",
            ),
        ),
    }

    result = evaluate_agent_batch(
        cases,
        resolve_run=lambda case: runs.get(case.case_id),
        resolve_events=lambda run: events[run.run_id],
    )

    assert result.total_cases == 2
    assert result.trajectory_case_count == 2
    assert result.react_run_rate == 1.0
    assert result.average_react_iterations == 2.5
    assert result.average_tool_calls == 1.5
    assert result.average_knowledge_searches == 1.5
    assert result.average_query_reformulations == 0.5
    assert result.average_novel_evidence == 1.0
    assert result.no_novel_evidence_run_rate == 0.5
    assert result.retrieval_fallback_run_rate == 0.5
    assert result.redundant_action_rate == 0.5
    assert result.react_limit_rate == 0.5
    assert result.grounded_rate == 0.5
    assert result.confirmation_guard_rate == 1.0

    grounded = result.results[0].trajectory
    assert grounded.knowledge_search_count == 2
    assert grounded.query_reformulation_count == 1
    assert grounded.novel_evidence_count == 2
    assert grounded.no_novel_evidence_search_count == 0
    assert grounded.retrieval_fallback_count == 0
