from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.models import RetrievalResult
from backend.rag.query_planner import RagQueryPlan

RAG_EVENT_TYPES = (
    "rag_query_started",
    "rag_query_rewritten",
    "rag_dense_completed",
    "rag_sparse_completed",
    "rag_fusion_completed",
    "rag_rerank_completed",
    "rag_evidence_selected",
    "rag_fallback",
)
MAX_TRACE_EXCERPT_CHARS = 160


class RagTraceEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(pattern=r"^rag_[a-z_]+$")
    payload: dict[str, Any] = Field(default_factory=dict)


def _metric(results: Sequence[RetrievalResult], key: str) -> float:
    return round(
        sum(float(result.metadata.get(key, 0.0) or 0.0) for result in results),
        3,
    )


def _count(results: Sequence[RetrievalResult], key: str) -> int:
    return sum(max(0, int(result.metadata.get(key, 0) or 0)) for result in results)


def _fallback_reason(
    results: Sequence[RetrievalResult], merged: RetrievalResult
) -> str:
    reasons: list[str] = []
    for result in (*results, merged):
        for key in ("fallback_reason", "reranker_fallback_reason"):
            reason = str(result.metadata.get(key, "") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
    return "; ".join(reasons)[:500]


def _evidence_summary(evidence: Sequence[AgentEvidenceItem]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": item.source_id,
            "chunk_id": item.evidence_id.removeprefix("evidence:"),
            "excerpt": item.excerpt.strip()[:MAX_TRACE_EXCERPT_CHARS],
            "score": item.score,
        }
        for item in evidence
    ]


def build_rag_trace_events(
    *,
    plan: RagQueryPlan,
    retrievals: Sequence[RetrievalResult],
    merged: RetrievalResult,
    evidence: Sequence[AgentEvidenceItem],
    query_id: str | None = None,
) -> list[RagTraceEventData]:
    identity = (query_id or f"rag-{uuid4().hex}")[:80]
    common = {"query_id": identity}
    events = [
        RagTraceEventData(
            event_type="rag_query_started",
            payload={**common, "retrieval_strategy": merged.retrieval_strategy},
        ),
        RagTraceEventData(
            event_type="rag_query_rewritten",
            payload={
                **common,
                "rewritten": plan.rewritten_query != plan.original_query,
                "subquery_count": len(plan.retrieval_queries),
            },
        ),
        RagTraceEventData(
            event_type="rag_dense_completed",
            payload={
                **common,
                "dense_count": _count(retrievals, "dense_count"),
                "embedding_ms": _metric(retrievals, "embedding_ms"),
                "dense_search_ms": _metric(retrievals, "dense_search_ms"),
            },
        ),
        RagTraceEventData(
            event_type="rag_sparse_completed",
            payload={
                **common,
                "sparse_count": _count(retrievals, "sparse_count"),
                "sparse_search_ms": _metric(retrievals, "sparse_search_ms"),
            },
        ),
        RagTraceEventData(
            event_type="rag_fusion_completed",
            payload={
                **common,
                "fusion_count": _count(retrievals, "fusion_count"),
                "fusion_ms": _metric(retrievals, "fusion_ms"),
            },
        ),
        RagTraceEventData(
            event_type="rag_rerank_completed",
            payload={
                **common,
                "final_count": len(merged.candidates),
                "rerank_ms": _metric(retrievals, "rerank_ms"),
            },
        ),
        RagTraceEventData(
            event_type="rag_evidence_selected",
            payload={
                **common,
                "final_count": len(evidence),
                "total_rag_ms": round(merged.elapsed_ms, 3),
                "evidence": _evidence_summary(evidence),
            },
        ),
    ]
    fallback_reason = _fallback_reason(retrievals, merged)
    if fallback_reason or not evidence:
        events.append(
            RagTraceEventData(
                event_type="rag_fallback",
                payload={
                    **common,
                    "fallback_reason": fallback_reason or "no_evidence",
                },
            )
        )
    return events


__all__ = [
    "MAX_TRACE_EXCERPT_CHARS",
    "RAG_EVENT_TYPES",
    "RagTraceEventData",
    "build_rag_trace_events",
]
