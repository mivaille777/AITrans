from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentConversationRole = Literal["user", "assistant", "system", "tool"]
AgentRouteKind = Literal["unresolved", "answer", "tool", "complex"]
AgentRouteSource = Literal[
    "none",
    "legacy_planner",
    "deterministic",
    "semantic_router",
    "planner",
]
AgentPlanMode = Literal["none", "single_step", "multi_step"]
AgentStepStatus = Literal["pending", "running", "completed", "failed", "skipped"]
AgentResponseStatus = Literal[
    "idle",
    "completed",
    "confirmation_required",
    "failed",
    "cancelled",
]


class AgentContractModel(BaseModel):
    """Base model for stable Agent runtime contracts."""

    model_config = ConfigDict(extra="forbid")


class AgentExecutionContext(AgentContractModel):
    run_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    request_id: int = Field(default=0, ge=0)


class AgentConversationMessage(AgentContractModel):
    role: AgentConversationRole
    content: str
    message_id: str = ""


class AgentConversationContext(AgentContractModel):
    conversation_id: str = ""
    history: list[AgentConversationMessage] = Field(default_factory=list)
    user_message_id: str = ""
    assistant_message_id: str = ""
    context_mode: Literal["general", "reading"] = "reading"


class AgentRequestContext(AgentContractModel):
    user_input: str = ""
    style: str = "academic"


class AgentReadingContext(AgentContractModel):
    source_text: str = ""
    translated_text: str = ""
    source_language: str = "auto"
    target_language: str = "zh-CN"
    resource_url: str = ""
    resource_title: str = ""
    section_heading: str = ""
    context_before: str = ""
    context_after: str = ""
    source_kind: str = "desktop"


class AgentRouteDecision(AgentContractModel):
    kind: AgentRouteKind = "unresolved"
    source: AgentRouteSource = "none"
    intent: str = ""
    tool_name: str = ""
    user_visible_reason: str = ""
    arguments: dict[str, str] = Field(default_factory=dict)


class AgentPlanStep(AgentContractModel):
    step_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    status: AgentStepStatus = "pending"


class AgentPlanContext(AgentContractModel):
    goal: str = ""
    mode: AgentPlanMode = "none"
    steps: list[AgentPlanStep] = Field(default_factory=list)
    current_step_id: str = ""


class AgentEvidenceItem(AgentContractModel):
    evidence_id: str
    source_type: str = ""
    source_id: str = ""
    title: str = ""
    resource_url: str = ""
    location: str = ""
    excerpt: str = ""
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCitationRef(AgentContractModel):
    citation_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    label: str = ""


class AgentResponseContext(AgentContractModel):
    status: AgentResponseStatus = "idle"
    output_text: str = ""
    provider: str = ""
    model: str = ""
    request_id: int = Field(default=0, ge=0)
    ui_mode: str = "assistant"


__all__ = [
    "AgentCitationRef",
    "AgentConversationContext",
    "AgentConversationMessage",
    "AgentEvidenceItem",
    "AgentExecutionContext",
    "AgentPlanContext",
    "AgentPlanMode",
    "AgentPlanStep",
    "AgentReadingContext",
    "AgentRequestContext",
    "AgentResponseContext",
    "AgentResponseStatus",
    "AgentRouteDecision",
    "AgentRouteKind",
    "AgentRouteSource",
    "AgentStepStatus",
]
