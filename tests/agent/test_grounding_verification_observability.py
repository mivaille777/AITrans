from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.state import AgentState
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.evaluation.agent_evaluator import AgentEvaluationExpectation, evaluate_agent_run
from backend.evaluation.dataset import load_evaluation_dataset, write_evaluation_dataset
from backend.evaluation.runner import evaluate_agent_batch
from backend.main import create_app
from backend.services.agent_trace_store_service import AgentTraceStoreService


def _event(
    state: AgentState,
    event_type: AgentEventType,
    elapsed_ms: int,
    **payload: object,
) -> AgentEvent:
    return AgentEvent(
        event_type=event_type,
        run_id=state.run_id,
        trace_id=state.trace_id,
        elapsed_ms=elapsed_ms,
        payload=dict(payload),
    )


def _verified_trace(
    state: AgentState,
    *,
    passed: bool,
    fallback_applied: bool,
) -> tuple[AgentEvent, ...]:
    return (
        _event(state, AgentEventType.AGENT_START, 0, budget_ms=45000),
        _event(
            state,
            AgentEventType.GROUNDING_VERIFICATION_EVALUATED,
            80,
            passed=passed,
            fallback_applied=fallback_applied,
            claim_count=2,
            cited_claim_count=2 if passed else 1,
            supported_claim_count=2 if passed else 1,
            unsupported_claim_count=0 if passed else 1,
            invalid_citation_count=0 if passed else 1,
            citation_coverage=1.0 if passed else 0.5,
            support_rate=1.0 if passed else 0.5,
            reason_codes=[] if passed else ["unknown_citation", "claim_support_below_policy"],
            request_id=17,
            claim_text="PRIVATE GENERATED CLAIM",
            evidence_excerpt="PRIVATE EVIDENCE EXCERPT",
            output_text="PRIVATE MODEL ANSWER",
        ),
        _event(
            state,
            AgentEventType.SYNTHESIS_READY,
            90,
            grounded=True,
            provider="policy" if fallback_applied else "stub",
            model="grounding-verification-fallback" if fallback_applied else "stub-model",
            request_id=17,
            duration_ms=20,
        ),
        _event(
            state,
            AgentEventType.AGENT_END,
            100,
            intent="complex",
            status="completed",
            ui_mode="research",
            total_duration_ms=100,
        ),
    )


def test_verification_trace_persists_only_aggregate_metrics(tmp_path) -> None:
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    state = AgentState(session_id="verified", intent="complex", ui_mode="research")
    store.record(state, _verified_trace(state, passed=False, fallback_applied=True))

    events = store.list_events(state.run_id)
    verification = next(
        event for event in events if event.event_type == "grounding_verification_evaluated"
    )

    assert verification.payload["passed"] is False
    assert verification.payload["fallback_applied"] is True
    assert verification.payload["claim_count"] == 2
    assert verification.payload["unsupported_claim_count"] == 1
    assert verification.payload["invalid_citation_count"] == 1
    assert verification.payload["citation_coverage"] == 0.5
    assert verification.payload["support_rate"] == 0.5
    serialized = repr(verification.payload)
    assert "PRIVATE GENERATED CLAIM" not in serialized
    assert "PRIVATE EVIDENCE EXCERPT" not in serialized
    assert "PRIVATE MODEL ANSWER" not in serialized


def test_evaluator_can_require_final_grounding_verification_pass(tmp_path) -> None:
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    passed_state = AgentState(session_id="pass", intent="complex", ui_mode="research")
    failed_state = AgentState(session_id="fail", intent="complex", ui_mode="research")
    passed_run = store.record(
        passed_state,
        _verified_trace(passed_state, passed=True, fallback_applied=False),
    )
    failed_run = store.record(
        failed_state,
        _verified_trace(failed_state, passed=False, fallback_applied=True),
    )
    expectation = AgentEvaluationExpectation(
        case_id="grounding",
        expected_intent="complex",
        require_grounded_response=True,
        require_grounding_verification_pass=True,
    )

    passed_result = evaluate_agent_run(
        passed_run,
        expectation,
        events=store.list_events(passed_run.run_id),
    )
    failed_result = evaluate_agent_run(
        failed_run,
        expectation,
        events=store.list_events(failed_run.run_id),
    )

    assert passed_result.passed is True
    assert passed_result.grounding_verification_pass is True
    assert passed_result.trajectory.grounding_verification_pass_count == 1
    assert passed_result.trajectory.average_citation_coverage == 1.0
    assert passed_result.trajectory.average_claim_support_rate == 1.0
    assert failed_result.passed is False
    assert failed_result.grounding_verification_pass is False
    assert failed_result.trajectory.grounding_verification_fallback_count == 1
    assert failed_result.trajectory.unsupported_claim_count == 1
    assert failed_result.trajectory.invalid_citation_count == 1


def test_batch_grounding_metrics_use_only_verified_runs_for_quality_rates(tmp_path) -> None:
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    passed_state = AgentState(session_id="pass", intent="complex", ui_mode="research")
    failed_state = AgentState(session_id="fail", intent="complex", ui_mode="research")
    fast_state = AgentState(session_id="fast", intent="answer", ui_mode="assistant")
    passed_run = store.record(
        passed_state,
        _verified_trace(passed_state, passed=True, fallback_applied=False),
    )
    failed_run = store.record(
        failed_state,
        _verified_trace(failed_state, passed=False, fallback_applied=True),
    )
    fast_run = store.record(
        fast_state,
        (
            _event(fast_state, AgentEventType.AGENT_START, 0, budget_ms=45000),
            _event(
                fast_state,
                AgentEventType.AGENT_END,
                20,
                intent="answer",
                status="completed",
                ui_mode="assistant",
                total_duration_ms=20,
            ),
        ),
    )
    runs = {
        "pass": passed_run,
        "fail": failed_run,
        "fast": fast_run,
    }
    cases = tuple(
        AgentEvaluationExpectation(case_id=case_id)
        for case_id in ("pass", "fail", "fast")
    )

    batch = evaluate_agent_batch(
        cases,
        resolve_run=lambda case: runs[case.case_id],
        resolve_events=lambda run: store.list_events(run.run_id),
    )

    assert batch.trajectory_case_count == 3
    assert batch.grounding_verification_run_rate == 0.6667
    assert batch.grounding_verification_pass_rate == 0.5
    assert batch.grounding_verification_fallback_rate == 0.5
    assert batch.average_citation_coverage == 0.75
    assert batch.average_claim_support_rate == 0.75
    assert batch.invalid_citation_run_rate == 0.5
    assert batch.unsupported_claim_run_rate == 0.5


def test_grounding_verification_expectation_round_trips_dataset(tmp_path) -> None:
    path = tmp_path / "eval.jsonl"
    case = AgentEvaluationExpectation(
        case_id="verified-grounding",
        require_grounded_response=True,
        require_grounding_verification_pass=True,
    )

    write_evaluation_dataset(path, (case,))
    loaded = load_evaluation_dataset(path)

    assert loaded[0].require_grounded_response is True
    assert loaded[0].require_grounding_verification_pass is True


def test_evaluation_api_exposes_grounding_verification_metrics(tmp_path) -> None:
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    state = AgentState(session_id="api", intent="complex", ui_mode="research")
    run = store.record(state, _verified_trace(state, passed=True, fallback_applied=False))

    app = create_app()
    app.dependency_overrides[get_agent_trace_store_service] = lambda: store
    client = TestClient(app)
    response = client.post(
        f"/api/agent/evaluation/run/{run.run_id}",
        json={
            "case_id": "verified-grounding",
            "expected_intent": "complex",
            "require_grounded_response": True,
            "require_grounding_verification_pass": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is True
    assert payload["grounding_verification_pass"] is True
    assert payload["trajectory"]["grounding_verification_count"] == 1
    assert payload["trajectory"]["final_grounding_verification_passed"] is True
    assert payload["trajectory"]["average_citation_coverage"] == 1.0
    assert payload["trajectory"]["average_claim_support_rate"] == 1.0
