from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    AGENT_START = "agent_start"
    CONTEXT_READY = "context_ready"
    KNOWLEDGE_RETRIEVAL_STARTED = "knowledge_retrieval_started"
    KNOWLEDGE_RETRIEVED = "knowledge_retrieved"
    KNOWLEDGE_CONTEXT_READY = "knowledge_context_ready"
    MULTI_AGENT_STARTED = "multi_agent_started"
    MULTI_AGENT_PLAN_READY = "multi_agent_plan_ready"
    MULTI_AGENT_KNOWLEDGE_STARTED = "multi_agent_knowledge_started"
    MULTI_AGENT_KNOWLEDGE_READY = "multi_agent_knowledge_ready"
    MULTI_AGENT_CONTEXT_READY = "multi_agent_context_ready"
    MULTI_AGENT_SPECIALIST_STARTED = "multi_agent_specialist_started"
    MULTI_AGENT_SPECIALIST_COMPLETED = "multi_agent_specialist_completed"
    MULTI_AGENT_SPECIALIST_FAILED = "multi_agent_specialist_failed"
    MULTI_AGENT_SPECIALIST_SKIPPED = "multi_agent_specialist_skipped"
    MULTI_AGENT_COMPLETED = "multi_agent_completed"
    PLAN_READY = "plan_ready"
    REACT_STARTED = "react_started"
    DECISION_READY = "decision_ready"
    TOOL_CALL = "tool_call"
    RETRY = "retry"
    TOOL_RESULT = "tool_result"
    OBSERVATION_READY = "observation_ready"
    EVIDENCE_GATE_EVALUATED = "evidence_gate_evaluated"
    REACT_LIMIT_REACHED = "react_limit_reached"
    RAG_QUERY_STARTED = "rag_query_started"
    RAG_QUERY_REWRITTEN = "rag_query_rewritten"
    RAG_DENSE_COMPLETED = "rag_dense_completed"
    RAG_SPARSE_COMPLETED = "rag_sparse_completed"
    RAG_FUSION_COMPLETED = "rag_fusion_completed"
    RAG_RERANK_COMPLETED = "rag_rerank_completed"
    RAG_EVIDENCE_SELECTED = "rag_evidence_selected"
    RAG_FALLBACK = "rag_fallback"
    SYNTHESIS_READY = "synthesis_ready"
    GROUNDING_VERIFICATION_EVALUATED = "grounding_verification_evaluated"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    AGENT_END = "agent_end"


class AgentEvent(BaseModel):
    event_type: AgentEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str = ""
    trace_id: str = ""
    elapsed_ms: int = Field(default=0, ge=0)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
