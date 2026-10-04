from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
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
    "rag_graph_completed",
    "rag_fusion_completed",
    "rag_rerank_completed",
    "rag_evidence_selected",
    "rag_fallback",
)
MAX_TRACE_EXCERPT_CHARS = 160

_RAG_TRACE: ContextVar[tuple[str | None, Any]] = ContextVar("rag_trace", default=(None, None))


@contextmanager
def bind_rag_trace(trace_id: str | None, event_sink: Any = None) -> Iterator[None]:
    token = _RAG_TRACE.set((trace_id, event_sink))
    try:
        yield
    finally:
        _RAG_TRACE.reset(token)


def current_rag_trace() -> tuple[str | None, Any]:
    return _RAG_TRACE.get()


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


def _chunk_ids(results: Sequence[RetrievalResult], key: str) -> list[str]:
    chunk_ids: list[str] = []
    seen: set[str] = set()
    for result in results:
        raw_ids = result.metadata.get(key, [])
        if not isinstance(raw_ids, list):
            continue
        for raw_id in raw_ids:
            chunk_id = str(raw_id).strip()
            if chunk_id and chunk_id not in seen:
                seen.add(chunk_id)
                chunk_ids.append(chunk_id)
    return chunk_ids


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
    trace_id: str | None = None,
) -> list[RagTraceEventData]:
    identity = (query_id or f"rag-{uuid4().hex}")[:80]
    scope = [result.metadata.get("allowed_document_ids") for result in retrievals]
    common = {"query_id": identity, "trace_id": trace_id or identity,
              "scope_hash": sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
              "generations": [result.metadata.get("active_generations") for result in retrievals],
              "retrieval_spans": [result.metadata["retrieval_span"] for result in retrievals if "retrieval_span" in result.metadata],
              "cache_hit": any(result.metadata.get("evidence_cache_hit", False) for result in retrievals),
              "cache_source_span_ids": [span_id for result in retrievals
                                        for span_id in result.metadata.get("cache_source_span_ids", [])],
              "token_usage": None, "cost": None}
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
            event_type="rag_graph_completed",
            payload={**common, "enabled": any(result.metadata.get("graph_enabled", False) for result in retrievals),
                     "graph_count": _count(retrievals, "graph_count"),
                     "graph_search_ms": _metric(retrievals, "graph_search_ms"),
                     "graph_trace": [result.metadata.get("graph_trace", {}) for result in retrievals],
                     "paths": [path.model_dump(mode="json") for candidate in merged.candidates for path in candidate.graph_paths]},
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
                "input_count": _count(retrievals, "rerank_candidate_count"),
                "output_count": sum(
                    len(result.metadata.get("post_rerank_chunk_ids", []))
                    for result in retrievals
                    if isinstance(
                        result.metadata.get("post_rerank_chunk_ids", []),
                        list,
                    )
                ),
                "final_count": len(merged.candidates),
                "rerank_ms": _metric(retrievals, "rerank_ms"),
                "input_chunk_ids": _chunk_ids(
                    retrievals,
                    "rerank_input_chunk_ids",
                ),
                "output_chunk_ids": _chunk_ids(
                    retrievals,
                    "post_rerank_chunk_ids",
                ),
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
    for index, event in enumerate(events):
        event.payload["event_id"] = f"{identity}:{index}"
        event.payload["parent_id"] = None if index == 0 else f"{identity}:0"
        event.payload["stage"] = event.event_type.removeprefix("rag_").removesuffix("_completed")
        stage = event.payload["stage"]
        stages = ("embedding", "dense") if stage == "dense" else (stage,)
        spans = [result.metadata["stage_timings"][key]
                 for result in retrievals for key in stages
                 if key in result.metadata.get("stage_timings", {})]
        if stage == "evidence_selected":
            spans = [span for result in retrievals for span in result.metadata.get("stage_timings", {}).values()]
        if spans:
            event.payload["spans"] = spans
            event.payload["started_at"] = min(span["started_at"] for span in spans)
            event.payload["ended_at"] = max(span["ended_at"] for span in spans)
    return events


__all__ = [
    "MAX_TRACE_EXCERPT_CHARS",
    "RAG_EVENT_TYPES",
    "RagTraceEventData",
    "build_rag_trace_events",
]
