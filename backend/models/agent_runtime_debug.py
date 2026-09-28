from __future__ import annotations

from pydantic import BaseModel, Field


class AgentCatalogEntry(BaseModel):
    agent_id: str
    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    version: str
    icon: str


class AgentCatalogResponse(BaseModel):
    agents: list[AgentCatalogEntry] = Field(default_factory=list)


class AgentRuntimeDebugRunSummary(BaseModel):
    run_id: str
    trace_id: str
    task_id: str | None = None
    status: str
    engine: str | None = None
    graph_version: str | None = None
    state_schema_version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    event_count: int | None = None
    failure_reason: str | None = None
    recovery_reason: str | None = None


class AgentRuntimeDebugArtifactRef(BaseModel):
    artifact_id: str
    version: int | None = None
    kind: str | None = None
    content_hash: str | None = None


class AgentRuntimeDebugAttempt(BaseModel):
    attempt: int | None = None
    status: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None


class AgentRuntimeDebugTask(BaseModel):
    task_id: str
    agent_id: str | None = None
    status: str | None = None
    depends_on: list[str] | None = None
    required: bool | None = None
    output_kind: str | None = None
    attempts: list[AgentRuntimeDebugAttempt] | None = None
    artifact_refs: list[AgentRuntimeDebugArtifactRef] | None = None
    duration_ms: int | None = None
    failure_reason: str | None = None


class AgentRuntimeDebugEvent(BaseModel):
    event_id: str
    sequence: int
    event_type: str
    timestamp: str
    task_id: str | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    node_name: str | None = None
    subgraph_path: str | None = None
    status: str | None = None
    attempt: int | None = None
    duration_ms: int | None = None
    tool_name: str | None = None
    reason_code: str | None = None
    recovery_reason: str | None = None


class AgentRuntimeDebugRoute(BaseModel):
    lane: str | None = None
    route_kind: str | None = None
    reason_code: str | None = None


class AgentRuntimeDebugPlan(BaseModel):
    plan_id: str | None = None
    plan_revision: int | None = None
    task_count: int | None = None


class AgentRuntimeDebugRelatedIds(BaseModel):
    rag_query_ids: list[str] | None = None
    sandbox_ids: list[str] | None = None


class AgentRuntimeDebugRunDetail(AgentRuntimeDebugRunSummary):
    route: AgentRuntimeDebugRoute | None = None
    plan: AgentRuntimeDebugPlan | None = None
    tasks: list[AgentRuntimeDebugTask] | None = None
    tool_names: list[str] | None = None
    related_ids: AgentRuntimeDebugRelatedIds = Field(
        default_factory=AgentRuntimeDebugRelatedIds
    )
    events: list[AgentRuntimeDebugEvent] = Field(default_factory=list)


__all__ = [
    "AgentCatalogEntry",
    "AgentCatalogResponse",
    "AgentRuntimeDebugArtifactRef",
    "AgentRuntimeDebugAttempt",
    "AgentRuntimeDebugEvent",
    "AgentRuntimeDebugPlan",
    "AgentRuntimeDebugRelatedIds",
    "AgentRuntimeDebugRoute",
    "AgentRuntimeDebugRunDetail",
    "AgentRuntimeDebugRunSummary",
    "AgentRuntimeDebugTask",
]
