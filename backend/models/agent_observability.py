from __future__ import annotations

from pydantic import BaseModel, Field


class AgentRunMetric(BaseModel):
    run_id: str
    trace_id: str
    session_id: str
    created_at: str
    status: str
    intent: str
    ui_mode: str
    tool_name: str
    provider: str
    model: str
    total_duration_ms: int = Field(ge=0)
    planning_duration_ms: int = Field(ge=0)
    tool_duration_ms: int = Field(ge=0)
    synthesis_duration_ms: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    timeout_count: int = Field(ge=0)
    fallback_reason: str
    event_count: int = Field(ge=0)


class AgentRecentRunsResponse(BaseModel):
    runs: list[AgentRunMetric] = Field(default_factory=list)


class AgentObservabilitySummaryResponse(BaseModel):
    sample_size: int = Field(ge=0)
    completed_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    cancelled_runs: int = Field(ge=0)
    confirmation_required_runs: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    schema_valid_rate: float = Field(ge=0.0, le=1.0)
    retry_rate: float = Field(ge=0.0, le=1.0)
    failure_rate: float = Field(ge=0.0, le=1.0)
    timeout_rate: float = Field(ge=0.0, le=1.0)
    fallback_rate: float = Field(ge=0.0, le=1.0)
    average_total_duration_ms: float = Field(ge=0.0)
    p95_total_duration_ms: int = Field(ge=0)
    average_planning_duration_ms: float = Field(ge=0.0)
    average_tool_duration_ms: float = Field(ge=0.0)
    average_synthesis_duration_ms: float = Field(ge=0.0)


class AgentEvaluationRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    expected_intent: str = Field(default="", max_length=128)
    expected_tool_name: str = Field(default="", max_length=128)
    expected_tool_sequence: list[str] = Field(default_factory=list, max_length=20)
    expected_status: str = Field(default="completed", max_length=64)
    expected_fallback_reason: str = Field(default="", max_length=128)
    expected_final_evidence_gate_action: str = Field(default="", max_length=32)
    expected_grounding_verification_pass: bool | None = None
    max_total_duration_ms: int = Field(default=0, ge=0)
    max_retry_count: int = Field(default=0, ge=0, le=10)
    require_zero_failures: bool = True
    expect_react: bool | None = None
    max_react_iterations: int = Field(default=0, ge=0, le=50)
    max_tool_calls: int = Field(default=0, ge=0, le=50)
    max_redundant_actions: int | None = Field(default=None, ge=0, le=50)
    require_no_react_limit: bool = False
    require_grounded_response: bool = False
    require_grounding_verification_pass: bool = False
    require_confirmation_guard: bool = False


class AgentTrajectoryMetricsResponse(BaseModel):
    available: bool
    react_started: bool
    react_iteration_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    tool_sequence: list[str] = Field(default_factory=list)
    redundant_action_count: int = Field(ge=0)
    react_limit_reached: bool
    react_limit_reason: str
    grounded: bool
    evidence_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    knowledge_search_count: int = Field(ge=0)
    query_reformulation_count: int = Field(ge=0)
    novel_evidence_count: int = Field(ge=0)
    no_novel_evidence_search_count: int = Field(ge=0)
    retrieval_fallback_count: int = Field(ge=0)
    evidence_gate_count: int = Field(ge=0)
    evidence_gate_stop_count: int = Field(ge=0)
    evidence_gate_refine_count: int = Field(ge=0)
    evidence_gate_retrieve_count: int = Field(ge=0)
    final_evidence_gate_action: str
    average_evidence_gate_quality_score: float = Field(ge=0.0, le=1.0)
    grounding_verification_count: int = Field(ge=0)
    grounding_verification_pass_count: int = Field(ge=0)
    grounding_verification_fallback_count: int = Field(ge=0)
    verified_claim_count: int = Field(ge=0)
    cited_claim_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    invalid_citation_count: int = Field(ge=0)
    average_citation_coverage: float = Field(ge=0.0, le=1.0)
    average_claim_support_rate: float = Field(ge=0.0, le=1.0)
    final_grounding_verification_passed: bool | None = None
    final_grounding_fallback_applied: bool | None = None
    confirmation_required_action_count: int = Field(ge=0)
    write_result_count: int = Field(ge=0)
    confirmation_guard_pass: bool


class AgentEvaluationResponse(BaseModel):
    case_id: str
    run_id: str
    trace_id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    intent_match: bool
    tool_match: bool
    status_match: bool
    fallback_match: bool
    latency_pass: bool
    retry_pass: bool
    failure_pass: bool
    react_mode_pass: bool
    tool_sequence_pass: bool
    react_iteration_pass: bool
    tool_call_pass: bool
    redundancy_pass: bool
    react_limit_pass: bool
    grounding_pass: bool
    evidence_gate_pass: bool
    grounding_verification_pass: bool
    confirmation_pass: bool
    trajectory: AgentTrajectoryMetricsResponse
    failures: list[str] = Field(default_factory=list)
