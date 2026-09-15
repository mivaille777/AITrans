from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.evaluation.agent_evaluator import AgentEvaluationExpectation, evaluate_agent_run
from backend.models.agent_observability import (
    AgentEvaluationRequest,
    AgentEvaluationResponse,
    AgentObservabilitySummaryResponse,
    AgentRecentRunsResponse,
    AgentRunMetric,
)
from backend.services.agent_trace_store_service import AgentTraceStoreService

router = APIRouter(prefix="/api/agent", tags=["agent-observability"])
AgentTraceStoreDependency = Annotated[
    AgentTraceStoreService,
    Depends(get_agent_trace_store_service),
]


@router.get(
    "/observability/recent",
    response_model=AgentRecentRunsResponse,
)
def list_recent_agent_runs(
    store: AgentTraceStoreDependency,
    limit: int = Query(default=20, ge=1, le=200),
) -> AgentRecentRunsResponse:
    return AgentRecentRunsResponse(
        runs=[AgentRunMetric(**asdict(run)) for run in store.list_recent(limit=limit)]
    )


@router.get(
    "/observability/summary",
    response_model=AgentObservabilitySummaryResponse,
)
def get_agent_observability_summary(
    store: AgentTraceStoreDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> AgentObservabilitySummaryResponse:
    summary = asdict(store.summary(limit=limit))
    runs = store.list_recent(limit=limit)
    schema_valid_count = sum(bool(run.intent.strip()) for run in runs)
    summary["schema_valid_rate"] = (
        round(schema_valid_count / len(runs), 4) if runs else 0.0
    )
    return AgentObservabilitySummaryResponse(**summary)


@router.post(
    "/evaluation/run/{run_id}",
    response_model=AgentEvaluationResponse,
)
def evaluate_persisted_agent_run(
    run_id: str,
    payload: AgentEvaluationRequest,
    store: AgentTraceStoreDependency,
) -> AgentEvaluationResponse:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent run not found: {run_id}",
        )

    result = evaluate_agent_run(
        run,
        AgentEvaluationExpectation(
            case_id=payload.case_id,
            expected_intent=payload.expected_intent,
            expected_tool_name=payload.expected_tool_name,
            expected_tool_sequence=tuple(payload.expected_tool_sequence),
            expected_status=payload.expected_status,
            expected_fallback_reason=payload.expected_fallback_reason,
            expected_final_evidence_gate_action=payload.expected_final_evidence_gate_action,
            expected_grounding_verification_pass=payload.expected_grounding_verification_pass,
            max_total_duration_ms=payload.max_total_duration_ms,
            max_retry_count=payload.max_retry_count,
            require_zero_failures=payload.require_zero_failures,
            expect_react=payload.expect_react,
            max_react_iterations=payload.max_react_iterations,
            max_tool_calls=payload.max_tool_calls,
            max_redundant_actions=payload.max_redundant_actions,
            require_no_react_limit=payload.require_no_react_limit,
            require_grounded_response=payload.require_grounded_response,
            require_grounding_verification_pass=payload.require_grounding_verification_pass,
            require_confirmation_guard=payload.require_confirmation_guard,
        ),
        events=store.list_events(run_id),
    )
    return AgentEvaluationResponse.model_validate(asdict(result))


__all__ = ["router"]
