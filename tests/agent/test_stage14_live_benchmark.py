from __future__ import annotations

from pathlib import Path

from backend.evaluation.agent_evaluator import AgentEvaluationExpectation
from backend.evaluation.live_benchmark import (
    execute_live_benchmark_case,
    load_live_benchmark_cases,
    validate_live_benchmark_coverage,
)
from backend.evaluation.runner import evaluate_agent_batch
from backend.evaluation.stage14_suite import prepare_stage14_runtime_cases
from backend.services.agent_trace_store_service import StoredAgentEvent, StoredAgentRun

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "backend/evaluation/datasets/stage14_live.jsonl"


def _case(case_id: str):
    cases = load_live_benchmark_cases(DATASET)
    return next(case for case in cases if case.case_id == case_id)


def _execute(case_id: str):
    case = prepare_stage14_runtime_cases((_case(case_id),))[0]
    return execute_live_benchmark_case(case)


def test_stage14_dataset_freezes_40_cases_across_required_categories() -> None:
    cases = load_live_benchmark_cases(DATASET)

    counts = validate_live_benchmark_coverage(cases)

    assert len(cases) == 40
    assert counts == {
        "confirmation": 3,
        "context_overflow": 3,
        "fallback": 3,
        "multi_step": 6,
        "prompt_injection": 3,
        "reading": 5,
        "research": 5,
        "summarization": 4,
        "tool_failure": 4,
        "translation": 4,
    }
    assert len({case.case_id for case in cases}) == 40


def test_live_harness_runs_real_retry_and_failure_boundaries() -> None:
    retried = _execute("translation-transient-retry")
    failed = _execute("tool-failure-translation-exhausted")

    assert retried.run.status == "completed"
    assert retried.run.retry_count == 1
    assert retried.run.failure_count == 0
    assert [
        event.event_type for event in retried.events if event.event_type == "retry"
    ] == ["retry"]

    assert failed.run.status == "failed"
    assert failed.run.retry_count == 1
    assert failed.run.failure_count == 1
    assert failed.run.fallback_reason == "safe_tool_retries_exhausted"
    assert any(event.event_type == "failure" for event in failed.events)


def test_prompt_injection_cannot_bypass_write_confirmation() -> None:
    execution = _execute("prompt-injection-write-confirmation")

    assert execution.run.status == "confirmation_required"
    assert execution.run.tool_name == "save_research_note"
    tool_calls = [event for event in execution.events if event.event_type == "tool_call"]
    tool_results = [event for event in execution.events if event.event_type == "tool_result"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["requires_confirmation"] is True
    assert tool_results == []


def test_agentic_rag_case_stops_on_evidence_gate_and_verifies_grounding() -> None:
    execution = _execute("multistep-search-refine-stop")

    assert execution.run.status == "completed"
    assert [
        event.payload.get("name")
        for event in execution.events
        if event.event_type == "tool_call"
    ] == ["search_knowledge_base", "search_knowledge_base"]
    gate_actions = [
        event.payload.get("action")
        for event in execution.events
        if event.event_type == "evidence_gate_evaluated"
    ]
    assert gate_actions == ["refine", "stop"]
    verification = next(
        event
        for event in execution.events
        if event.event_type == "grounding_verification_evaluated"
    )
    assert verification.payload["passed"] is True
    assert verification.payload["fallback_applied"] is False


def test_react_limit_case_stops_after_one_observation() -> None:
    execution = _execute("fallback-react-iteration-limit")

    assert execution.run.status == "completed"
    assert [
        event.payload.get("name")
        for event in execution.events
        if event.event_type == "tool_call"
    ] == ["inspect_reading_context"]
    limit = next(
        event for event in execution.events if event.event_type == "react_limit_reached"
    )
    assert limit.payload["reason"] == "iteration_budget_exhausted"


def _run(
    run_id: str,
    *,
    status: str,
    duration: int,
    fallback: str = "",
    retries: int = 0,
    failures: int = 0,
) -> StoredAgentRun:
    return StoredAgentRun(
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        session_id="stage14-metrics",
        created_at="2026-08-28T00:00:00+00:00",
        status=status,
        intent="answer",
        ui_mode="assistant",
        tool_name="",
        provider="fixture",
        model="fixture",
        total_duration_ms=duration,
        planning_duration_ms=0,
        tool_duration_ms=0,
        synthesis_duration_ms=duration,
        retry_count=retries,
        failure_count=failures,
        timeout_count=0,
        fallback_reason=fallback,
        event_count=2,
    )


def _events(run_id: str, prompt: int, completion: int) -> tuple[StoredAgentEvent, ...]:
    return (
        StoredAgentEvent(
            sequence=0,
            event_type="agent_end",
            timestamp="",
            elapsed_ms=1,
            payload={"intent": "answer"},
        ),
        StoredAgentEvent(
            sequence=1,
            event_type="benchmark_usage",
            timestamp="",
            elapsed_ms=1,
            payload={
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            },
        ),
    )


def test_batch_reports_stage14_operational_metrics_and_reported_tokens() -> None:
    cases = (
        AgentEvaluationExpectation(case_id="ok", expected_status="completed"),
        AgentEvaluationExpectation(
            case_id="safe-failure",
            expected_status="failed",
            expected_fallback_reason="safe_fallback",
            max_retry_count=1,
            require_zero_failures=False,
        ),
    )
    runs = {
        "ok": _run("ok", status="completed", duration=100),
        "safe-failure": _run(
            "safe-failure",
            status="failed",
            duration=500,
            fallback="safe_fallback",
            retries=1,
            failures=1,
        ),
    }
    event_map = {
        "ok": _events("ok", 100, 50),
        "safe-failure": _events("safe-failure", 80, 20),
    }

    batch = evaluate_agent_batch(
        cases,
        resolve_run=lambda case: runs.get(case.case_id),
        resolve_events=lambda run: event_map[run.run_id],
    )

    assert batch.pass_rate == 1.0
    assert batch.task_completion_rate == 0.5
    assert batch.fallback_rate == 0.5
    assert batch.tool_failure_rate == 0.5
    assert batch.retry_rate == 0.5
    assert batch.latency_p50_ms == 100
    assert batch.latency_p95_ms == 500
    assert batch.token_usage_available_rate == 1.0
    assert batch.total_prompt_tokens == 180
    assert batch.total_completion_tokens == 70
    assert batch.total_tokens == 250
    assert batch.average_total_tokens == 125.0
