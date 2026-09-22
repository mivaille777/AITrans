from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.rag.config import RagConfig

RagDebugRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
RagDebugStageStatus = Literal[
    "pending", "active", "complete", "warning", "failed", "skipped"
]
RagDebugStageKey = Literal[
    "query", "rewrite", "dense", "bm25", "fusion", "rerank", "context", "answer"
]


class RagDebugModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagDebugCompanionTrace(RagDebugModel):
    trace_id: str
    request_id: int = Field(default=0, ge=0)
    conversation_id: str = ""
    query: str = ""
    knowledge_enabled: bool = False
    document_scope: str = "off"
    route: str
    route_reason: str = ""
    grounding_policy: str
    retrieval_skipped: bool
    verification_skipped: bool
    catalog_document_count: int = Field(default=0, ge=0)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    fallback_applied: bool = False
    created_at: str


class RagDebugRunRequest(RagDebugModel):
    query: str = Field(min_length=1, max_length=4_000)
    config_id: str = Field(default="default", min_length=1, max_length=128)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=8, ge=1, le=100)
    include_answer: bool = False
    workspace_id: str = Field(default="", max_length=128)
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO


class RagDebugStageEvent(RagDebugModel):
    sequence: int = Field(ge=0)
    stage: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)


class RagDebugStage(RagDebugModel):
    key: RagDebugStageKey
    label: str
    status: RagDebugStageStatus
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    note: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    candidate_count: int = Field(default=0, ge=0)


class RagDebugCandidate(RagDebugModel):
    id: str = Field(min_length=1)
    document_id: str = ""
    source: str = ""
    section: str = ""
    page: int | None = Field(default=None, ge=1)
    tokens: int = Field(default=0, ge=0)
    dense: float | None = None
    bm25: float | None = None
    fusion: float | None = None
    rerank: float | None = None
    before: int | None = Field(default=None, ge=1)
    after: int | None = Field(default=None, ge=1)
    text: str = ""
    chunk_type: str = ""
    start: int = Field(default=0, ge=0)
    end: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagDebugContext(RagDebugModel):
    text: str = ""
    estimated_tokens: int = Field(default=0, ge=0)
    included_evidence_ids: list[str] = Field(default_factory=list)
    omitted_evidence_ids: list[str] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)


class RagDebugTraceResponse(RagDebugModel):
    run_id: str
    trace_id: str
    status: RagDebugRunStatus
    query: str
    config_id: str
    query_plan: dict[str, Any] = Field(default_factory=dict)
    stages: list[RagDebugStage] = Field(default_factory=list)
    candidates: list[RagDebugCandidate] = Field(default_factory=list)
    context: RagDebugContext = Field(default_factory=RagDebugContext)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    answer: str = ""
    knowledge_decision: dict[str, Any] = Field(default_factory=dict)
    knowledge_scope: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class RagDebugRunAccepted(RagDebugModel):
    run_id: str
    trace_id: str
    status: RagDebugRunStatus


class RagDebugRunEventsResponse(RagDebugModel):
    run_id: str
    trace_id: str
    status: RagDebugRunStatus
    events: list[RagDebugStageEvent] = Field(default_factory=list)


class RagDebugConfigProfile(RagDebugModel):
    config_id: str
    name: str
    description: str = ""
    config: RagConfig
    active: bool = False
    requires_reindex: bool = False
    index_fingerprint: str = ""
    created_at: str
    updated_at: str


class RagDebugConfigCreate(RagDebugModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    config: RagConfig = Field(default_factory=RagConfig)
    activate: bool = False


class RagDebugConfigUpdate(RagDebugModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    config: RagConfig | None = None
    activate: bool | None = None


class RagDebugConfigActivation(RagDebugModel):
    config_id: str
    active: bool


class RagDebugDocument(RagDebugModel):
    document_id: str
    title: str = ""
    source_uri: str = ""
    status: str = ""
    chunk_count: int = Field(default=0, ge=0)
    updated_at: str = ""


class RagDebugChunk(RagDebugModel):
    id: str
    document_id: str
    title: str = ""
    preview: str = ""
    section: str = ""
    section_path: list[str] = Field(default_factory=list)
    page: int | None = Field(default=None, ge=1)
    tokens: int = Field(default=0, ge=0)
    overlap: int = Field(default=0, ge=0)
    start: int = Field(default=0, ge=0)
    end: int = Field(default=0, ge=0)
    type: str = ""
    embedding: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagDebugChunkPage(RagDebugModel):
    chunks: list[RagDebugChunk] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class RagDebugDataset(RagDebugModel):
    dataset_id: str
    name: str
    description: str = ""
    case_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str


class RagDebugDatasetCreate(RagDebugModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class RagDebugCase(RagDebugModel):
    case_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4_000)
    categories: list[str] = Field(default_factory=list, max_length=20)
    relevant_chunk_ids: list[str] = Field(default_factory=list, max_length=100)
    relevance_grades: dict[str, int] = Field(default_factory=dict)
    claims: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    no_answer: bool = False
    # Optional routing annotations.  Older datasets remain valid: the
    # evaluator derives expected_retrieval from no_answer and derives a
    # document scope from metadata.document_id when these are omitted.
    expected_retrieval: bool | None = None
    expected_scope_document_ids: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, str] = Field(default_factory=dict)
    query_type: str = "Factual"
    expected_answer: str = ""
    answerable: bool = True
    tags: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=20_000)
    updated_at: str = ""


class RagDebugDatasetImport(RagDebugModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=5_000_000)
    format: Literal["json", "jsonl"] | None = None


class RagDebugDatasetExport(RagDebugModel):
    dataset: RagDebugDataset
    format: Literal["json", "jsonl"]
    content: str


class RagDebugEvaluationRequest(RagDebugModel):
    dataset_id: str
    config_id: str = "default"
    top_k: int = Field(default=20, ge=1, le=100)
    case_ids: list[str] = Field(default_factory=list, max_length=500)


class RagDebugEvaluationResponse(RagDebugModel):
    dataset_id: str
    config_id: str
    report: dict[str, Any]


class RagDebugCompareRequest(RagDebugModel):
    dataset_id: str
    baseline_config_id: str = "default"
    candidate_config_id: str
    top_k: int = Field(default=20, ge=1, le=100)
    case_ids: list[str] = Field(default_factory=list, max_length=500)


class RagDebugCompareCase(RagDebugModel):
    case_id: str
    query: str
    baseline_rank: int | None = None
    candidate_rank: int | None = None
    baseline_latency_ms: float = Field(default=0.0, ge=0.0)
    candidate_latency_ms: float = Field(default=0.0, ge=0.0)
    baseline_chunk_ids: list[str] = Field(default_factory=list)
    candidate_chunk_ids: list[str] = Field(default_factory=list)


class RagDebugCompareResponse(RagDebugModel):
    dataset_id: str
    baseline_config_id: str
    candidate_config_id: str
    cases: list[RagDebugCompareCase] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "RagDebugCandidate",
    "RagDebugCase",
    "RagDebugChunk",
    "RagDebugChunkPage",
    "RagDebugCompanionTrace",
    "RagDebugCompareCase",
    "RagDebugCompareRequest",
    "RagDebugCompareResponse",
    "RagDebugConfigActivation",
    "RagDebugConfigCreate",
    "RagDebugConfigProfile",
    "RagDebugConfigUpdate",
    "RagDebugContext",
    "RagDebugDataset",
    "RagDebugDatasetCreate",
    "RagDebugDatasetExport",
    "RagDebugDatasetImport",
    "RagDebugDocument",
    "RagDebugEvaluationRequest",
    "RagDebugEvaluationResponse",
    "RagDebugRunAccepted",
    "RagDebugRunEventsResponse",
    "RagDebugRunRequest",
    "RagDebugRunStatus",
    "RagDebugStage",
    "RagDebugStageEvent",
    "RagDebugTraceResponse",
]
