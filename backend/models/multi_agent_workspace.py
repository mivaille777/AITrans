from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MultiAgentRunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=12000)
    user_id: str = Field(default="", max_length=256)


class MultiAgentPlanStep(BaseModel):
    agent: str


class MultiAgentResultResponse(BaseModel):
    agent_name: str
    output: Any = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MultiAgentTraceEventResponse(BaseModel):
    sequence: int = Field(ge=0)
    event_type: str
    actor: str
    status: str
    timestamp: str
    elapsed_ms: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class MultiAgentContextSnapshot(BaseModel):
    knowledge_context_chars: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    memory_keys: list[str] = Field(default_factory=list)
    intermediate_agents: list[str] = Field(default_factory=list)


class MultiAgentRunTraceResponse(BaseModel):
    run_id: str
    trace_id: str
    total_duration_ms: int = Field(ge=0)
    plan: list[MultiAgentPlanStep] = Field(default_factory=list)
    results: list[MultiAgentResultResponse] = Field(default_factory=list)
    context: MultiAgentContextSnapshot
    events: list[MultiAgentTraceEventResponse] = Field(default_factory=list)


__all__ = [
    "MultiAgentContextSnapshot",
    "MultiAgentPlanStep",
    "MultiAgentResultResponse",
    "MultiAgentRunRequest",
    "MultiAgentRunTraceResponse",
    "MultiAgentTraceEventResponse",
]
