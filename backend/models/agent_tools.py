from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.models.agent_runtime import (
    AgentCitationRef,
    AgentEvidenceItem,
    AgentPlanContext,
)
from backend.models.quick_actions import ReadingContextPayload

AgentToolEffect = Literal["read", "compute", "write"]
AgentRunStatus = Literal["completed", "confirmation_required"]
AgentPlanAction = Literal["answer", "tool"]
AgentClientSurface = Literal["main", "overlay", "unknown"]
AgentContextMode = Literal["general", "reading", "knowledge", "research", "translation"]
AgentTraceEventType = Literal[
    "agent_start",
    "context_ready",
    "plan_ready",
    "tool_call",
    "retry",
    "tool_result",
    "rag_query_started",
    "rag_query_rewritten",
    "rag_dense_completed",
    "rag_sparse_completed",
    "rag_fusion_completed",
    "rag_rerank_completed",
    "rag_evidence_selected",
    "rag_fallback",
    "synthesis_ready",
    "failure",
    "cancelled",
    "agent_end",
]


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
    ai_action: str = Field(default="", max_length=128)
    conversation_id: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", max_length=128)
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
    def validate_tool_action(self) -> "AgentPlan":
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
    client_id: str = Field(default="", max_length=128)
    client_surface: AgentClientSurface = "unknown"
    context_mode: AgentContextMode = "reading"
    user_message: str = Field(min_length=1, max_length=20_000)
    style: str = Field(default="academic", min_length=1, max_length=64)
    conversation_id: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", max_length=128)
    confirmed_write_tools: list[str] = Field(default_factory=list, max_length=16)
    knowledge_document_ids: list[str] = Field(default_factory=list, max_length=100)
    research_source_ids: list[str] = Field(default_factory=list, max_length=100)
    request_id: int = Field(default=0, ge=0)


class AgentRunResponse(BaseModel):
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
