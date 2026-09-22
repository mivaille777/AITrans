from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock
from time import perf_counter
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from backend.models.knowledge_access import (
    KnowledgeAccessPolicy,
    KnowledgeScopeStrategy,
)
from backend.models.rag_debug import (
    RagDebugCandidate,
    RagDebugCase,
    RagDebugChunk,
    RagDebugChunkPage,
    RagDebugCompanionTrace,
    RagDebugCompareCase,
    RagDebugCompareResponse,
    RagDebugConfigProfile,
    RagDebugContext,
    RagDebugDocument,
    RagDebugRunAccepted,
    RagDebugRunEventsResponse,
    RagDebugRunRequest,
    RagDebugStage,
    RagDebugStageEvent,
    RagDebugTraceResponse,
)
from backend.rag.citation_service import build_evidence_citations
from backend.rag.config import RagConfig
from backend.rag.context_builder import GroundedContextBuilder
from backend.rag.evaluation import evaluate_rag
from backend.rag.evaluation_dataset import (
    RagEvaluationCase,
    RagEvaluationClaim,
    RagEvaluationLatency,
    RagEvaluationPrediction,
)
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.observability import build_rag_trace_events
from backend.rag.query_planner import RagQueryPlanner, merge_query_results
from backend.rag.retrieval_service import RetrievalService
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.structure_retrieval import (
    build_structural_queries,
    detect_structural_intent,
    promote_structural_candidates,
)
from backend.services.knowledge_access_router import KnowledgeAccessRouter
from backend.services.knowledge_scope_resolver import KnowledgeScopeResolver
from backend.services.rag_debug_store_service import RagDebugStoreService

_STAGE_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("query", "Query", "Parse query and intent"),
    ("rewrite", "Rewrite", "Generate standalone retrieval queries"),
    ("dense", "Dense Retrieval", "Vector search from the active index"),
    ("bm25", "BM25 Retrieval", "Sparse lexical search from the active index"),
    ("fusion", "Fusion", "Merge retrieval lists with the configured strategy"),
    ("rerank", "Rerank", "Apply the configured reranker when available"),
    ("context", "Context Building", "Build bounded grounded context"),
    ("answer", "Answer Generation", "Optional answer generation from context"),
)
_VALID_CATEGORIES = {
    "term",
    "exact_identifier",
    "cross_section",
    "multilingual",
    "multi_document",
    "no_answer",
}


@dataclass
class _RunState:
    response: RagDebugTraceResponse
    events: list[RagDebugStageEvent]
    cancel: Event


class _RunCancelled(Exception):
    pass


class RagDebugService:
    """Coordinates real RAG inspection without changing the production path."""

    def __init__(self, *, store: RagDebugStoreService) -> None:
        self.store = store
        self._lock = RLock()
        self._runs: dict[str, _RunState] = {}
        self._companion_traces: list[RagDebugCompanionTrace] = []
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-debug")

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


    def record_companion_route(
        self,
        *,
        request_id: int,
        conversation_id: str,
        query: str,
        knowledge_enabled: bool,
        document_ids: tuple[str, ...],
        route: str,
        route_reason: str,
        grounding_policy: str,
        retrieval_skipped: bool,
        verification_skipped: bool,
        catalog_document_count: int = 0,
        retrieval: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> str:
        trace_id = f"companion_{uuid4().hex[:20]}"
        scope = (
            "selected"
            if document_ids
            else ("all" if knowledge_enabled else "off")
        )
        trace = RagDebugCompanionTrace(
            trace_id=trace_id,
            request_id=max(0, int(request_id or 0)),
            conversation_id=str(conversation_id or "")[:128],
            query=str(query or "")[:4000],
            knowledge_enabled=bool(knowledge_enabled),
            document_scope=scope,
            route=str(route or ""),
            route_reason=str(route_reason or ""),
            grounding_policy=str(grounding_policy or ""),
            retrieval_skipped=bool(retrieval_skipped),
            verification_skipped=bool(verification_skipped),
            catalog_document_count=max(0, int(catalog_document_count or 0)),
            retrieval=dict(retrieval or {}),
            evidence=[dict(item) for item in (evidence or [])][:20],
            citations=[dict(item) for item in (citations or [])][:20],
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._companion_traces.insert(0, trace)
            del self._companion_traces[100:]
        return trace_id

    def update_companion_verification(
        self,
        trace_id: str,
        *,
        verification: dict[str, Any] | None,
        fallback_applied: bool,
    ) -> None:
        with self._lock:
            for index, trace in enumerate(self._companion_traces):
                if trace.trace_id != trace_id:
                    continue
                self._companion_traces[index] = trace.model_copy(
                    update={
                        "verification_skipped": False,
                        "verification": dict(verification or {}),
                        "fallback_applied": bool(fallback_applied),
                    }
                )
                break

    def list_companion_traces(self, *, limit: int = 20) -> list[RagDebugCompanionTrace]:
        safe_limit = max(1, min(int(limit or 20), 100))
        with self._lock:
            return [
                item.model_copy(deep=True)
                for item in self._companion_traces[:safe_limit]
            ]

    def ensure_default_config(self, runtime_config: RagConfig) -> RagDebugConfigProfile:
        return self.store.ensure_default_config(runtime_config)

    def start_trace(
        self,
        request: RagDebugRunRequest,
        *,
        runtime: Any,
        answer_service: Any | None = None,
    ) -> RagDebugRunAccepted:
        run_id = f"ragrun_{uuid4().hex[:20]}"
        trace_id = f"ragtrace_{uuid4().hex[:20]}"
        initial = RagDebugTraceResponse(
            run_id=run_id,
            trace_id=trace_id,
            status="queued",
            query=request.query.strip(),
            config_id=request.config_id,
            stages=self._initial_stages(),
        )
        state = _RunState(response=initial, events=[], cancel=Event())
        with self._lock:
            self._runs[run_id] = state
        self._executor.submit(
            self._execute_background,
            run_id,
            request,
            runtime,
            answer_service,
        )
        return RagDebugRunAccepted(run_id=run_id, trace_id=trace_id, status="queued")

    def get_run(self, run_id: str) -> RagDebugTraceResponse | None:
        with self._lock:
            state = self._runs.get(run_id)
            return state.response.model_copy(deep=True) if state else None

    def get_events(self, run_id: str, after: int = 0) -> RagDebugRunEventsResponse | None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return None
            return RagDebugRunEventsResponse(
                run_id=run_id,
                trace_id=state.response.trace_id,
                status=state.response.status,
                events=[event.model_copy(deep=True) for event in state.events if event.sequence > after],
            )

    def cancel(self, run_id: str) -> RagDebugTraceResponse | None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return None
            if state.response.status not in {"completed", "failed", "cancelled"}:
                state.cancel.set()
                state.response = state.response.model_copy(update={"status": "cancelled"})
            return state.response.model_copy(deep=True)

    def list_documents(self, runtime: Any) -> list[RagDebugDocument]:
        documents: list[RagDebugDocument] = []
        for record in runtime.manifest.list_records():
            status = getattr(record.status, "value", record.status)
            documents.append(
                RagDebugDocument(
                    document_id=record.document_id,
                    title=record.title,
                    source_uri=record.source_uri,
                    status=str(status or ""),
                    chunk_count=len(record.chunk_ids),
                    updated_at=record.indexed_at,
                )
            )
        return documents

    def list_chunks(
        self,
        runtime: Any,
        *,
        document_id: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> RagDebugChunkPage:
        raw_chunks = getattr(runtime.sparse_retriever, "list_chunks", list)()
        normalized_document = document_id.strip()
        normalized_query = query.strip().casefold()
        filtered = [
            chunk
            for chunk in raw_chunks
            if (not normalized_document or chunk.document_id == normalized_document)
            and (
                not normalized_query
                or normalized_query in chunk.text.casefold()
                or normalized_query in chunk.title.casefold()
                or normalized_query in chunk.section_heading.casefold()
            )
        ]
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 200))
        start = (safe_page - 1) * safe_size
        return RagDebugChunkPage(
            chunks=[self._chunk_response(chunk, runtime) for chunk in filtered[start : start + safe_size]],
            total=len(filtered),
            page=safe_page,
            page_size=safe_size,
        )

    def get_chunk(self, runtime: Any, chunk_id: str) -> RagDebugChunk | None:
        getter = getattr(runtime.sparse_retriever, "get_chunk", None)
        chunk = getter(chunk_id) if callable(getter) else runtime.vector_store.get_chunk(chunk_id)
        return self._chunk_response(chunk, runtime) if chunk is not None else None

    def run_trace_sync(
        self,
        request: RagDebugRunRequest,
        *,
        runtime: Any,
        answer_service: Any | None = None,
    ) -> RagDebugTraceResponse:
        run_id = f"rageval_{uuid4().hex[:20]}"
        trace_id = f"ragtrace_{uuid4().hex[:20]}"
        return self._execute_core(
            run_id=run_id,
            trace_id=trace_id,
            request=request,
            runtime=runtime,
            answer_service=answer_service,
            cancelled=Event(),
            emit=lambda _stage, _status, _payload: None,
        )

    def evaluate_dataset(
        self,
        *,
        dataset_id: str,
        config_id: str,
        top_k: int,
        case_ids: list[str],
        runtime: Any,
    ) -> dict[str, Any]:
        cases = self.store.list_cases(dataset_id)
        selected = [case for case in cases if not case_ids or case.case_id in set(case_ids)]
        predictions: list[RagEvaluationPrediction] = []
        summaries: list[dict[str, Any]] = []
        for case in selected:
            evaluation_policy = (
                KnowledgeAccessPolicy.AUTO
                if case.no_answer
                else KnowledgeAccessPolicy.ALWAYS
            )
            trace = self.run_trace_sync(
                RagDebugRunRequest(
                    query=case.query,
                    config_id=config_id,
                    top_k=top_k,
                    include_answer=False,
                    # Answerable cases measure retrieval quality and must not be
                    # short-circuited by the runtime's auto knowledge gate.
                    # No-answer cases retain auto so the existing abstention
                    # metric can still observe an empty retrieval result.
                    knowledge_access_policy=evaluation_policy,
                ),
                runtime=runtime,
            )
            ranked = [candidate.id for candidate in trace.candidates]
            metadata = trace.metadata
            predictions.append(
                RagEvaluationPrediction(
                    case_id=case.case_id,
                    ranked_chunk_ids=ranked,
                    pre_rerank_chunk_ids=ranked,
                    latency=RagEvaluationLatency(
                        query_embedding_ms=float(metadata.get("embedding_ms", 0.0) or 0.0),
                        dense_search_ms=float(metadata.get("dense_search_ms", 0.0) or 0.0),
                        bm25_ms=float(metadata.get("sparse_search_ms", 0.0) or 0.0),
                        rerank_ms=float(metadata.get("rerank_ms", 0.0) or 0.0),
                        total_rag_ms=float(metadata.get("total_rag_ms", 0.0) or 0.0),
                    ),
                )
            )
            summaries.append(
                {
                    "case_id": case.case_id,
                    "query": case.query,
                    "type": case.query_type,
                    "answerable": case.answerable,
                    "tags": case.tags,
                }
            )
        evaluation_cases = [self._evaluation_case(case) for case in selected]
        report = evaluate_rag(evaluation_cases, predictions).model_dump(mode="json")
        report["case_details"] = summaries
        return report

    def compare_dataset(
        self,
        *,
        dataset_id: str,
        baseline_config_id: str,
        candidate_config_id: str,
        top_k: int,
        case_ids: list[str],
        runtime: Any,
    ) -> RagDebugCompareResponse:
        cases = self.store.list_cases(dataset_id)
        selected = [case for case in cases if not case_ids or case.case_id in set(case_ids)]
        compared: list[RagDebugCompareCase] = []
        baseline_hits: list[float] = []
        candidate_hits: list[float] = []
        for case in selected:
            evaluation_policy = (
                KnowledgeAccessPolicy.AUTO
                if case.no_answer
                else KnowledgeAccessPolicy.ALWAYS
            )
            baseline = self.run_trace_sync(
                RagDebugRunRequest(
                    query=case.query,
                    config_id=baseline_config_id,
                    top_k=top_k,
                    knowledge_access_policy=evaluation_policy,
                ),
                runtime=runtime,
            )
            candidate = self.run_trace_sync(
                RagDebugRunRequest(
                    query=case.query,
                    config_id=candidate_config_id,
                    top_k=top_k,
                    knowledge_access_policy=evaluation_policy,
                ),
                runtime=runtime,
            )
            baseline_ids = [item.id for item in baseline.candidates]
            candidate_ids = [item.id for item in candidate.candidates]
            baseline_rank = self._first_rank(baseline_ids, case.relevant_chunk_ids)
            candidate_rank = self._first_rank(candidate_ids, case.relevant_chunk_ids)
            baseline_hits.append(float(bool(baseline_rank and baseline_rank <= 10)))
            candidate_hits.append(float(bool(candidate_rank and candidate_rank <= 10)))
            compared.append(
                RagDebugCompareCase(
                    case_id=case.case_id,
                    query=case.query,
                    baseline_rank=baseline_rank,
                    candidate_rank=candidate_rank,
                    baseline_latency_ms=float(baseline.metadata.get("total_rag_ms", 0.0) or 0.0),
                    candidate_latency_ms=float(candidate.metadata.get("total_rag_ms", 0.0) or 0.0),
                    baseline_chunk_ids=baseline_ids,
                    candidate_chunk_ids=candidate_ids,
                )
            )
        baseline_recall = sum(baseline_hits) / len(baseline_hits) if baseline_hits else 0.0
        candidate_recall = sum(candidate_hits) / len(candidate_hits) if candidate_hits else 0.0
        return RagDebugCompareResponse(
            dataset_id=dataset_id,
            baseline_config_id=baseline_config_id,
            candidate_config_id=candidate_config_id,
            cases=compared,
            metrics={
                "baseline_recall_at_10": baseline_recall,
                "candidate_recall_at_10": candidate_recall,
                "recall_delta": candidate_recall - baseline_recall,
                "evaluated_cases": len(selected),
            },
        )

    def _execute_background(
        self,
        run_id: str,
        request: RagDebugRunRequest,
        runtime: Any,
        answer_service: Any | None,
    ) -> None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return
            state.response = state.response.model_copy(update={"status": "running"})

        def emit(stage: str, status: str, payload: dict[str, Any]) -> None:
            self._update_run(run_id, stage, status, payload)

        try:
            response = self._execute_core(
                run_id=run_id,
                trace_id=self._runs[run_id].response.trace_id,
                request=request,
                runtime=runtime,
                answer_service=answer_service,
                cancelled=self._runs[run_id].cancel,
                emit=emit,
            )
            with self._lock:
                state = self._runs.get(run_id)
                if state is not None:
                    state.response = response.model_copy(
                        update={"status": "cancelled" if state.cancel.is_set() else "completed"}
                    )
        except _RunCancelled:
            with self._lock:
                state = self._runs.get(run_id)
                if state is not None:
                    state.response = state.response.model_copy(update={"status": "cancelled"})
        except Exception as exc:  # noqa: BLE001 - expose a bounded diagnostic to the UI
            with self._lock:
                state = self._runs.get(run_id)
                if state is not None:
                    state.response = state.response.model_copy(
                        update={"status": "failed", "error": str(exc) or exc.__class__.__name__}
                    )
                    self._append_event(
                        state,
                        "trace",
                        "failed",
                        {"error": str(exc) or exc.__class__.__name__},
                    )

    def _execute_core(
        self,
        *,
        run_id: str,
        trace_id: str,
        request: RagDebugRunRequest,
        runtime: Any,
        answer_service: Any | None,
        cancelled: Event,
        emit: Callable[[str, str, dict[str, Any]], None],
    ) -> RagDebugTraceResponse:
        started = perf_counter()
        profile = self.store.get_config(request.config_id)
        if profile is None and request.config_id == "default":
            profile = self.ensure_default_config(runtime.config)
        if profile is None:
            raise KeyError(f"RAG config profile not found: {request.config_id}")
        response_stages = self._initial_stages()

        knowledge_context_mode = "research" if request.workspace_id.strip() else "knowledge"
        knowledge_decision_model = KnowledgeAccessRouter().route(
            user_message=request.query,
            context_mode=knowledge_context_mode,
            policy=request.knowledge_access_policy,
            reading_context_available=False,
            attached_document="",
            explicit_scope_count=len(request.document_ids),
            workspace_available=bool(request.workspace_id.strip()),
            knowledge_available=True,
            context_summary="RAG Debug Studio retrieval trace",
        )
        knowledge_scope_model = KnowledgeScopeResolver().resolve(
            context_mode=knowledge_context_mode,
            explicit_document_ids=request.document_ids,
            attached_document_id="",
            workspace_id=request.workspace_id,
            workspace_document_ids=request.document_ids,
            research_source_ids=(),
            global_allowed=knowledge_decision_model.scope_strategy is KnowledgeScopeStrategy.GLOBAL_KNOWLEDGE,
            requested_strategy=knowledge_decision_model.scope_strategy,
        )
        knowledge_decision = knowledge_decision_model.model_dump(mode="json")
        knowledge_decision["query_chars"] = len(knowledge_decision_model.query)
        knowledge_scope = knowledge_scope_model.model_dump(mode="json")
        emit(
            "knowledge_decision",
            "complete",
            knowledge_decision,
        )
        emit(
            "knowledge_scope",
            "complete",
            knowledge_scope,
        )

        def check_cancelled() -> None:
            if cancelled.is_set():
                raise _RunCancelled()

        def stage_update(key: str, status: str, *, summary: dict[str, Any] | None = None, elapsed_ms: float = 0.0, count: int = 0) -> None:
            stage = next(item for item in response_stages if item.key == key)
            stage.status = status  # type: ignore[misc]
            stage.elapsed_ms = max(0.0, float(elapsed_ms))
            stage.summary = summary or {}
            stage.candidate_count = max(0, int(count))
            emit(key, status, {"summary": stage.summary, "candidate_count": stage.candidate_count})

        stage_update("query", "active")
        query_plan = RagQueryPlanner(text_service=None).plan(request.query)
        stage_update(
            "query",
            "complete",
            summary={"original_query": query_plan.original_query},
        )
        stage_update(
            "rewrite",
            "complete",
            summary={
                "rewritten_query": query_plan.rewritten_query,
                "retrieval_queries": list(query_plan.retrieval_queries),
            },
        )
        check_cancelled()

        if not knowledge_decision_model.should_retrieve:
            for key in ("dense", "bm25", "fusion", "rerank", "context", "answer"):
                stage_update(
                    key,
                    "skipped",
                    summary={"reason": knowledge_decision_model.reason_code},
                )
            return RagDebugTraceResponse(
                run_id=run_id,
                trace_id=trace_id,
                status="completed",
                query=request.query,
                config_id=profile.config_id,
                query_plan=query_plan.model_dump(mode="json"),
                stages=response_stages,
                knowledge_decision=knowledge_decision,
                knowledge_scope=knowledge_scope,
                metadata={
                    "knowledge_access_policy": request.knowledge_access_policy.value,
                    "retrieval_skipped": True,
                    "retrieval_round_count": 0,
                    "retrieval_queries": [],
                    "skip_reason": knowledge_decision_model.reason_code,
                },
            )

        structural_intent = detect_structural_intent(request.query) or detect_structural_intent(query_plan.rewritten_query)
        retrieval_queries = build_structural_queries(
            query_plan.retrieval_queries,
            original_query=request.query,
            intent=structural_intent,
        )
        scope_document_ids = list(dict.fromkeys(knowledge_scope_model.document_ids))
        filters = VectorSearchFilter(document_ids=scope_document_ids) if scope_document_ids else None
        retriever = self._retriever_for_profile(runtime, profile)
        retrievals: list[RetrievalResult] = []
        retrieval_errors: list[str] = []
        dense_started = perf_counter()
        for retrieval_query in retrieval_queries:
            check_cancelled()
            kwargs: dict[str, Any] = {"filters": filters, "final_top_k": request.top_k}
            if structural_intent is not None:
                kwargs["section_hints"] = structural_intent.section_aliases
                kwargs["include_references"] = structural_intent.name == "bibliography"
            try:
                retrievals.append(retriever.retrieve(retrieval_query, **kwargs))
            except Exception as exc:  # noqa: BLE001 - show partial debug failures
                retrieval_errors.append(str(exc) or exc.__class__.__name__)

        if not retrievals:
            raise RuntimeError("; ".join(retrieval_errors) or "RAG retrieval returned no result.")

        elapsed_retrieval = (perf_counter() - dense_started) * 1000
        dense_count = sum(int(result.metadata.get("dense_count", 0) or 0) for result in retrievals)
        sparse_count = sum(int(result.metadata.get("sparse_count", 0) or 0) for result in retrievals)
        stage_update("dense", "complete", elapsed_ms=elapsed_retrieval, count=dense_count, summary={"count": dense_count, "embedding_ms": self._metric(retrievals, "embedding_ms"), "dense_search_ms": self._metric(retrievals, "dense_search_ms")})
        stage_update("bm25", "complete", elapsed_ms=elapsed_retrieval, count=sparse_count, summary={"count": sparse_count, "sparse_search_ms": self._metric(retrievals, "sparse_search_ms")})

        merge_limit = max(1, min(request.top_k, max(len(item.candidates) for item in retrievals)))
        merged = merge_query_results(request.query, retrievals, limit=merge_limit)
        merged = promote_structural_candidates(merged, intent=structural_intent, limit=merge_limit)
        stage_update("fusion", "complete", elapsed_ms=self._metric(retrievals, "fusion_ms"), count=len(merged.candidates), summary={"count": len(merged.candidates), "strategy": merged.retrieval_strategy})
        rerank_fallback = "; ".join(str(item.metadata.get("reranker_fallback_reason", "") or "") for item in retrievals if item.metadata.get("reranker_fallback_reason"))
        stage_update("rerank", "warning" if rerank_fallback else "complete", elapsed_ms=self._metric(retrievals, "rerank_ms"), count=len(merged.candidates), summary={"count": len(merged.candidates), "fallback": rerank_fallback})
        check_cancelled()

        evidence = build_agent_evidence(merged)
        citations = build_evidence_citations(evidence)
        grounded = GroundedContextBuilder().build(evidence, citations)
        stage_update("context", "complete", elapsed_ms=(perf_counter() - started) * 1000 - sum(item.elapsed_ms for item in response_stages[:6]), count=len(evidence), summary={"estimated_tokens": grounded.estimated_tokens, "included": len(grounded.included_evidence_ids), "omitted": len(grounded.omitted_evidence_ids)})

        answer = ""
        answer_status = "skipped"
        answer_summary: dict[str, Any] = {"enabled": request.include_answer}
        if request.include_answer:
            if answer_service is None:
                answer_status = "warning"
                answer_summary["error"] = "Answer service is unavailable."
            else:
                try:
                    answer_result = answer_service.send(
                        session_id=f"rag-debug:{run_id}",
                        user_message=request.query,
                        context_mode="knowledge",
                        tool_context=grounded.text,
                        knowledge_enabled=False,
                    )
                    answer = str(answer_result.output_text or "")
                    answer_status = "complete"
                    answer_summary["model"] = answer_result.model
                except Exception as exc:  # noqa: BLE001 - retrieval remains useful if generation fails
                    answer_status = "warning"
                    answer_summary["error"] = str(exc) or exc.__class__.__name__
        stage_update("answer", answer_status, elapsed_ms=(perf_counter() - started) * 1000, summary=answer_summary)

        trace_events = build_rag_trace_events(
            plan=query_plan,
            retrievals=retrievals,
            merged=merged,
            evidence=evidence,
            query_id=trace_id,
        )
        for event in trace_events:
            emit(event.event_type, "complete", event.payload)

        candidates = self._candidate_responses(merged, retrievals)
        metadata = {
            "total_rag_ms": (perf_counter() - started) * 1000,
            "embedding_ms": self._metric(retrievals, "embedding_ms"),
            "dense_search_ms": self._metric(retrievals, "dense_search_ms"),
            "sparse_search_ms": self._metric(retrievals, "sparse_search_ms"),
            "fusion_ms": self._metric(retrievals, "fusion_ms"),
            "rerank_ms": self._metric(retrievals, "rerank_ms"),
            "retrieval_strategy": merged.retrieval_strategy,
            "retrieval_queries": list(retrieval_queries),
            "retrieval_errors": retrieval_errors,
            "fallback_reason": "; ".join(retrieval_errors),
            "config_requires_reindex": profile.requires_reindex,
            "config_index_fingerprint": profile.index_fingerprint,
            "knowledge_access_policy": request.knowledge_access_policy.value,
            "knowledge_decision": knowledge_decision,
            "knowledge_scope": knowledge_scope,
            "retrieval_skipped": False,
            "retrieval_round_count": len(retrieval_queries),
        }
        return RagDebugTraceResponse(
            run_id=run_id,
            trace_id=trace_id,
            status="completed",
            query=request.query,
            config_id=profile.config_id,
            query_plan=query_plan.model_dump(mode="json"),
            stages=response_stages,
            candidates=candidates,
            context=RagDebugContext(
                text=grounded.text,
                estimated_tokens=grounded.estimated_tokens,
                included_evidence_ids=list(grounded.included_evidence_ids),
                omitted_evidence_ids=list(grounded.omitted_evidence_ids),
                source_count=len(evidence),
            ),
            evidence=[item.model_dump(mode="json") for item in evidence],
            citations=[item.model_dump(mode="json") for item in citations],
            answer=answer,
            knowledge_decision=knowledge_decision,
            knowledge_scope=knowledge_scope,
            metadata=metadata,
        )

    def _update_run(self, run_id: str, stage: str, status: str, payload: dict[str, Any]) -> None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return
            if state.response.status == "cancelled":
                return
            if stage in {item.key for item in state.response.stages}:
                stages = list(state.response.stages)
                index = next(index for index, item in enumerate(stages) if item.key == stage)
                current = stages[index]
                stages[index] = current.model_copy(
                    update={
                        "status": status,
                        "summary": dict(payload.get("summary") or {}),
                        "candidate_count": max(0, int(payload.get("candidate_count", 0) or 0)),
                    }
                )
                state.response = state.response.model_copy(update={"stages": stages})
            self._append_event(state, stage, status, payload)

    @staticmethod
    def _append_event(state: _RunState, stage: str, status: str, payload: dict[str, Any]) -> None:
        sequence = len(state.events)
        state.events.append(
            RagDebugStageEvent(
                sequence=sequence,
                stage=stage,
                status=status,
                elapsed_ms=0.0,
                payload=payload,
            )
        )

    @staticmethod
    def _initial_stages() -> list[RagDebugStage]:
        return [
            RagDebugStage(key=key, label=label, status="pending", note=note)
            for key, label, note in _STAGE_DEFINITIONS
        ]

    @staticmethod
    def _metric(results: list[RetrievalResult], key: str) -> float:
        return round(sum(float(item.metadata.get(key, 0.0) or 0.0) for item in results), 3)

    @staticmethod
    def _retriever_for_profile(runtime: Any, profile: RagDebugConfigProfile) -> Any:
        base = getattr(runtime.retrieval_service, "_base", runtime.retrieval_service)
        current_config = getattr(base, "_config", runtime.config.retrieval)
        if profile.config.retrieval == current_config:
            return runtime.retrieval_service
        return RetrievalService(
            embedding_provider=runtime.embedding_provider,
            vector_store=runtime.vector_store,
            sparse_retriever=runtime.sparse_retriever,
            config=profile.config.retrieval,
            reranker=getattr(base, "_reranker", None),
        )

    @classmethod
    def _candidate_responses(
        cls,
        merged: RetrievalResult,
        retrievals: list[RetrievalResult],
    ) -> list[RagDebugCandidate]:
        before_rank: dict[str, int] = {}
        for result in retrievals:
            for candidate in result.candidates:
                chunk_id = candidate.chunk.chunk_id
                rank = candidate.rank or 0
                if rank > 0:
                    before_rank[chunk_id] = min(before_rank.get(chunk_id, rank), rank)
        return [
            cls._candidate_response(candidate, before_rank.get(candidate.chunk.chunk_id))
            for candidate in merged.candidates
        ]

    @staticmethod
    def _candidate_response(candidate: RetrievalCandidate, before: int | None = None) -> RagDebugCandidate:
        chunk = candidate.chunk
        return RagDebugCandidate(
            id=chunk.chunk_id,
            document_id=chunk.document_id,
            source=RagDebugService._source_name(chunk),
            section=chunk.section_heading or " / ".join(chunk.section_path),
            page=chunk.page_number,
            tokens=chunk.token_count,
            dense=candidate.dense_score,
            bm25=candidate.sparse_score,
            fusion=candidate.fusion_score,
            rerank=candidate.rerank_score,
            before=before or candidate.rank,
            after=candidate.rank,
            text=chunk.text,
            chunk_type=chunk.chunk_type,
            start=chunk.start_char,
            end=chunk.end_char,
            metadata=candidate.metadata,
        )

    @staticmethod
    def _chunk_response(chunk: DocumentChunk | None, runtime: Any) -> RagDebugChunk:
        if chunk is None:
            raise ValueError("chunk must not be empty")
        return RagDebugChunk(
            id=chunk.chunk_id,
            document_id=chunk.document_id,
            title=chunk.title,
            preview=chunk.text[:220].strip() + ("…" if len(chunk.text) > 220 else ""),
            section=chunk.section_heading or " / ".join(chunk.section_path),
            section_path=list(chunk.section_path),
            page=chunk.page_number,
            tokens=chunk.token_count,
            overlap=int(chunk.metadata.get("overlap_tokens", 0) or 0),
            start=chunk.start_char,
            end=chunk.end_char,
            type=chunk.chunk_type,
            embedding=runtime.config.embedding.model,
            text=chunk.text,
            metadata=chunk.metadata,
        )

    @staticmethod
    def _source_name(chunk: DocumentChunk) -> str:
        raw = str(chunk.source_uri or "").strip()
        if raw.startswith("file:"):
            path = unquote(urlparse(raw).path)
            return Path(path).name or chunk.document_id
        return Path(raw).name if raw else chunk.document_id

    @staticmethod
    def _evaluation_case(case: RagDebugCase) -> RagEvaluationCase:
        categories = [item for item in case.categories if item in _VALID_CATEGORIES]
        if case.no_answer and "no_answer" not in categories:
            categories.append("no_answer")
        claims = [RagEvaluationClaim.model_validate(item) for item in case.claims]
        return RagEvaluationCase(
            case_id=case.case_id,
            query=case.query,
            categories=categories,
            relevant_chunk_ids=[] if case.no_answer else case.relevant_chunk_ids,
            relevance_grades={} if case.no_answer else case.relevance_grades,
            claims=claims,
            no_answer=case.no_answer,
            metadata=case.metadata,
        )

    @staticmethod
    def _first_rank(ranked: list[str], relevant: list[str]) -> int | None:
        wanted = set(relevant)
        for index, chunk_id in enumerate(ranked, start=1):
            if chunk_id in wanted:
                return index
        return None


async def wait_for_run_terminal(service: RagDebugService, run_id: str) -> RagDebugTraceResponse | None:
    while True:
        response = service.get_run(run_id)
        if response is None or response.status in {"completed", "failed", "cancelled"}:
            return response
        await asyncio.sleep(0.12)


__all__ = ["RagDebugService", "wait_for_run_terminal"]
