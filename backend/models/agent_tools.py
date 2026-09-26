from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.models.agent_runtime import (
    AgentCitationRef,
    AgentEvidenceItem,
    AgentPlanContext,
)
from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.models.quick_actions import ReadingContextPayload

AgentToolEffect = Literal["read", "compute", "write"]
AgentRunStatus = Literal["completed", "confirmation_required"]
AgentPlanAction = Literal["answer", "tool"]
AgentClientSurface = Literal["main", "overlay", "unknown"]
AgentContextMode = Literal["general", "reading", "knowledge", "research", "translation"]
AgentWorkflowAction = Literal[
    "",
    "quick_read",
    "analyze_visuals",
    "compare_papers",
    "curate_knowledge",
    "draft_section",
]
AgentTraceEventType = Literal[
    "agent_start",
    "context_ready",
    "knowledge_retrieval_started",
    "knowledge_retrieved",
    "knowledge_context_ready",
    "knowledge_decision",
    "knowledge_scope_resolved",
    "knowledge_skipped",
    "multi_agent_started",
    "multi_agent_plan_ready",
    "multi_agent_knowledge_started",
    "multi_agent_knowledge_ready",
    "multi_agent_context_ready",
    "multi_agent_specialist_started",
    "multi_agent_specialist_completed",
    "multi_agent_specialist_failed",
    "multi_agent_specialist_skipped",
    "multi_agent_completed",
    "task_planned",
    "task_ready",
    "task_started",
    "task_progress",
    "task_completed",
    "task_partial",
    "task_failed",
    "task_blocked",
    "task_cancelled",
    "task_skipped",
    "task_retrying",
    "plan_revised",
    "budget_exhausted",
    "artifact_verified",
    "artifact_rejected",
    "workflow_partial",
    "workflow_resumed",
    "plan_ready",
    "react_started",
    "decision_ready",
    "tool_call",
    "retry",
    "tool_result",
    "observation_ready",
    "evidence_gate_evaluated",
    "evidence_sufficiency",
    "react_limit_reached",
    "rag_query_started",
    "rag_query_rewritten",
    "rag_dense_completed",
    "rag_sparse_completed",
    "rag_fusion_completed",
    "rag_rerank_completed",
    "rag_evidence_selected",
    "rag_fallback",
    "synthesis_ready",
    "grounding_verification_evaluated",
    "failure",
    "cancelled",
    "agent_end",
]


class AgentKnowledgeCanvasContext(BaseModel):
    board_id: str = Field(default="", max_length=128)
    board_name: str = Field(default="", max_length=512)
    scope_label: str = Field(default="", max_length=256)


class AgentKnowledgeCardContext(BaseModel):
    item_id: str = Field(max_length=128)
    item_type: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=1024)
    summary: str = Field(default="", max_length=8000)
    document_id: str = Field(default="", max_length=256)


class AgentKnowledgeRelationContext(BaseModel):
    relation_id: str = Field(max_length=128)
    source_item_id: str = Field(max_length=128)
    source_title: str = Field(default="", max_length=1024)
    target_item_id: str = Field(max_length=128)
    target_title: str = Field(default="", max_length=1024)
    relation_type: str = Field(max_length=128)
    label: str = Field(default="", max_length=1024)
    origin: str = Field(default="", max_length=64)
    confidence: float | None = None


class AgentKnowledgeContext(BaseModel):
    canvas: AgentKnowledgeCanvasContext | None = None
    cards: list[AgentKnowledgeCardContext] = Field(default_factory=list, max_length=60)
    relations: list[AgentKnowledgeRelationContext] = Field(
        default_factory=list, max_length=60
    )


class AgentToolDefinition(BaseModel):
    name: str
    title: str
    description: str
    category: str
    effect: AgentToolEffect
    requires_reading_context: bool = True
    requires_confirmation: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)


class AgentToolCatalogResponse(BaseModel):
    tools: list[AgentToolDefinition]


class AgentToolExecuteRequest(ReadingContextPayload):
    style: str = Field(default="academic", min_length=1, max_length=64)
    user_note: str = Field(default="", max_length=20_000)
    ai_content: str = Field(default="", max_length=30_000)
    code: str = Field(default="", max_length=50_000)
    ai_action: str = Field(default="", max_length=128)
    conversation_id: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", max_length=128)
    filesystem_workspace_id: str = Field(default="", max_length=128)
    request_id: int = Field(default=0, ge=0)


class AgentToolExecuteResponse(BaseModel):
    tool_name: str
    output_text: str
    effect: AgentToolEffect
    provider: str = ""
    model: str = ""
    request_id: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    action: AgentPlanAction
    tool_name: str = Field(default="", max_length=128)
    user_visible_reason: str = Field(default="", max_length=500)
    arguments: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tool_action(self) -> AgentPlan:
        if self.action == "tool" and not self.tool_name.strip():
            raise ValueError("Agent tool plan requires tool_name.")
        if self.action == "answer":
            self.tool_name = ""
            self.arguments = {}
        return self


class AgentRunRequest(ReadingContextPayload):
    # Agent runs may be context-free. ReadingContextPayload is reused for the
    # bounded field set, but a General/Knowledge/Research request must not be
    # forced to attach an ambient reading selection just to satisfy validation.
    source_text: str = Field(default="", max_length=20_000)
    session_id: str = Field(default="agent-session", min_length=1, max_length=128)
    trace_id: str = Field(default="", max_length=128)
    resume_run_id: str = Field(default="", max_length=128)
    client_id: str = Field(default="", max_length=128)
    client_surface: AgentClientSurface = "unknown"
    context_mode: AgentContextMode = "reading"
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_enabled: bool | None = None
    user_message: str = Field(min_length=1, max_length=20_000)
    style: str = Field(default="academic", min_length=1, max_length=64)
    conversation_id: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", max_length=128)
    filesystem_workspace_id: str = Field(default="", max_length=128)
    confirmed_write_tools: list[str] = Field(default_factory=list, max_length=16)
    enabled_tools: list[str] = Field(default_factory=list, max_length=64)
    knowledge_document_ids: list[str] = Field(default_factory=list, max_length=100)
    explicit_knowledge_document_ids: list[str] = Field(default_factory=list, max_length=100)
    attached_document_id: str = Field(default="", max_length=256)
    research_source_ids: list[str] = Field(default_factory=list, max_length=100)
    knowledge_context: AgentKnowledgeContext | None = None
    knowledge_item_id: str = Field(default="", max_length=128)
    knowledge_writeback_type: str = Field(default="", max_length=64)
    knowledge_writeback_operation: str = Field(default="", max_length=128)
    knowledge_relation_type: str = Field(default="", max_length=128)
    request_id: int = Field(default=0, ge=0)
    temporary: bool = False
    workflow_action: AgentWorkflowAction = ""
    retry_task_id: str = Field(default="", max_length=256)

    @model_validator(mode="after")
    def migrate_legacy_knowledge_toggle(self) -> AgentRunRequest:
        """Translate the legacy Boolean toggle only when no new policy was sent."""

        if (
            self.knowledge_enabled is not None
            and "knowledge_access_policy" not in self.model_fields_set
        ):
            self.knowledge_access_policy = (
                KnowledgeAccessPolicy.ALWAYS
                if self.knowledge_enabled
                else KnowledgeAccessPolicy.NEVER
            )
        self.attached_document_id = self.attached_document_id.strip()
        self.filesystem_workspace_id = self.filesystem_workspace_id.strip()
        return self


class AgentRunResponse(BaseModel):
    run_id: str = ""
    trace_id: str = ""
    status: AgentRunStatus
    plan: AgentPlan
    multi_step_plan: AgentPlanContext | None = None
    output_text: str = ""
    provider: str = ""
    model: str = ""
    request_id: int = 0
    conversation_id: str = ""
    tool_result: AgentToolExecuteResponse | None = None
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)


class AgentTraceEvent(BaseModel):
    sequence: int = Field(ge=0)
    event_type: AgentTraceEventType
    timestamp: str
    run_id: str = ""
    trace_id: str = ""
    elapsed_ms: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunTraceResponse(BaseModel):
    run_id: str
    trace_id: str
    session_id: str
    ui_mode: str = "idle"
    total_duration_ms: int = Field(default=0, ge=0)
    run: AgentRunResponse
    events: list[AgentTraceEvent] = Field(default_factory=list)


class AgentRunSnapshotResponse(BaseModel):
    run_id: str
    trace_id: str
    status: str
    scope: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    events: list[AgentTraceEvent] = Field(default_factory=list)
    resumable: bool = False
    retryable_task_ids: list[str] = Field(default_factory=list)
