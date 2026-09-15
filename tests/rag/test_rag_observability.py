from __future__ import annotations

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.state import AgentState
from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.observability import (
    MAX_TRACE_EXCERPT_CHARS,
    RAG_EVENT_TYPES,
    build_rag_trace_events,
)
from backend.rag.query_planner import RagQueryPlan
from backend.services.agent_trace_store_service import AgentTraceStoreService


def _candidate(chunk_id: str = "chunk-1", text: str = "Bounded evidence"):
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id="document-1",
            text=text,
            title="Control Paper",
            source_uri="file:///control.pdf",
            chunk_index=0,
        ),
        rank=1,
        fusion_score=0.7,
        rerank_score=0.9,
    )


def _retrieval(*, candidates=None, fallback_reason="") -> RetrievalResult:
    return RetrievalResult(
        query="PRIVATE FULL QUERY",
        candidates=list(candidates if candidates is not None else [_candidate()]),
        retrieval_strategy="hybrid",
        elapsed_ms=24.5,
        metadata={
            "dense_count": 5,
            "sparse_count": 4,
            "fusion_count": 6,
            "final_count": 1,
            "embedding_ms": 3.0,
            "dense_search_ms": 4.0,
            "sparse_search_ms": 5.0,
            "fusion_ms": 1.0,
            "rerank_ms": 7.0,
            "fallback_reason": fallback_reason,
        },
    )


def _evidence(excerpt: str = "Bounded evidence") -> AgentEvidenceItem:
    return AgentEvidenceItem(
        evidence_id="evidence:chunk-1",
        source_type="knowledge",
        source_id="document-1",
        title="Control Paper",
        resource_url="file:///control.pdf",
        excerpt=excerpt,
        score=0.9,
    )


def _plan() -> RagQueryPlan:
    return RagQueryPlan(
        original_query="PRIVATE FULL QUERY",
        rewritten_query="PRIVATE REWRITTEN QUERY",
        subqueries=["PRIVATE SUBQUERY A", "PRIVATE SUBQUERY B"],
    )


def _events(*, retrieval=None, evidence=None):
    result = retrieval or _retrieval()
    return build_rag_trace_events(
        plan=_plan(),
        retrievals=[result],
        merged=result,
        evidence=[_evidence()] if evidence is None else evidence,
        query_id="rag-test-1",
    )


def test_success_trace_contains_one_event_per_retrieval_stage() -> None:
    events = _events()
    event_types = [event.event_type for event in events]

    assert event_types == list(RAG_EVENT_TYPES[:-1])
    assert len(event_types) == len(set(event_types))
    assert events[2].payload == {
        "query_id": "rag-test-1",
        "dense_count": 5,
        "embedding_ms": 3.0,
        "dense_search_ms": 4.0,
    }
    assert events[-1].payload["total_rag_ms"] == 24.5


def test_degraded_retrieval_emits_bounded_fallback_trace() -> None:
    events = _events(retrieval=_retrieval(fallback_reason="dense unavailable"))

    fallback = events[-1]
    assert fallback.event_type == "rag_fallback"
    assert fallback.payload["fallback_reason"] == "dense unavailable"


def test_no_evidence_emits_selection_and_fallback_without_duplicates() -> None:
    result = _retrieval(candidates=[])
    events = _events(retrieval=result, evidence=[])
    event_types = [event.event_type for event in events]

    assert "rag_evidence_selected" in event_types
    assert event_types[-1] == "rag_fallback"
    assert events[-1].payload["fallback_reason"] == "no_evidence"
    assert len(event_types) == len(set(event_types))


def test_sensitive_payload_is_bounded_and_omits_full_queries(tmp_path) -> None:
    events = _events(evidence=[_evidence("S" * 500)])
    selected = next(
        event for event in events if event.event_type == "rag_evidence_selected"
    )
    summary = selected.payload["evidence"][0]
    assert len(summary["excerpt"]) == MAX_TRACE_EXCERPT_CHARS
    assert summary["document_id"] == "document-1"
    assert summary["chunk_id"] == "chunk-1"

    state = AgentState(session_id="rag-session", intent="search_knowledge_base")
    trace = [
        AgentEvent(
            event_type=AgentEventType(event.event_type),
            payload=event.payload,
            run_id=state.run_id,
            trace_id=state.trace_id,
            elapsed_ms=index,
        )
        for index, event in enumerate(events)
    ]
    trace.append(
        AgentEvent(
            event_type=AgentEventType.AGENT_END,
            payload={"status": "completed", "intent": "search_knowledge_base"},
            run_id=state.run_id,
            trace_id=state.trace_id,
            elapsed_ms=len(trace),
        )
    )
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    store.record(state, trace)
    persisted = repr(store.event_payloads(state.run_id))

    assert "PRIVATE FULL QUERY" not in persisted
    assert "PRIVATE REWRITTEN QUERY" not in persisted
    assert "PRIVATE SUBQUERY" not in persisted
    assert "S" * MAX_TRACE_EXCERPT_CHARS in persisted
    assert "S" * (MAX_TRACE_EXCERPT_CHARS + 1) not in persisted
