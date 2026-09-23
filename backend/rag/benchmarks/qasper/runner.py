from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from app.ai.chat.models import ChatContext, ChatRequest
from app.ai.chat.service import AIChatService
from app.ai.gateway import LLMGateway
from backend.models.agent_react import AgentRetrievalObservation
from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.benchmarks.cache import qasper_sample_hash
from backend.rag.benchmarks.common import (
    atomic_write_json,
    atomic_write_jsonl,
    benchmark_root,
    read_json,
)
from backend.rag.benchmarks.qasper.ablation import (
    QASPER_ABLATION_VARIANTS,
    QasperAblationVariant,
    get_qasper_ablation_variant,
)
from backend.rag.benchmarks.qasper.alignment import align_qasper_evidence
from backend.rag.benchmarks.qasper.index import build_qasper_index
from backend.rag.benchmarks.qasper.sampling import sample_qasper_dataset
from backend.rag.benchmarks.qasper.schema import QasperDataset, QasperQuestion
from backend.rag.citation_service import build_evidence_citations
from backend.rag.config import RagConfig
from backend.rag.embeddings import EmbeddingProvider, create_embedding_provider
from backend.rag.evaluation import percentile
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.evidence_requirements import (
    EvidenceRequirement,
    assess_evidence_requirements,
    evidence_requirement_coverage,
    infer_evidence_requirements,
)
from backend.rag.evidence_selection import (
    EvidenceExcerptProvider,
    EvidenceSelectionService,
)
from backend.rag.fusion import rrf_fuse
from backend.rag.model_manager import ModelManager
from backend.rag.models import RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import RagQueryPlan, merge_query_results
from backend.rag.raptor import (
    ExtractiveRaptorSummaryProvider,
    RaptorSearchHit,
    RaptorSummaryProvider,
    RaptorTree,
    RaptorTreeBuilder,
    rank_summary_nodes,
)
from backend.rag.rerankers import Qwen3RerankerProvider
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.structure_retrieval import detect_structural_intent
from backend.services.agent_evidence_gate_service import AgentEvidenceGateService
from backend.services.grounded_synthesis_service import GroundedSynthesisService

RUN_LIMITS: dict[str, int | None] = {
    "smoke": 20,
    "dev": 100,
    "full": None,
}
BENCHMARK_FINAL_TOP_K = 20
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class QasperGeneratedAnswer:
    answer: str
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] | None = None


class QasperAnswerer(Protocol):
    def __call__(
        self,
        question: QasperQuestion,
        retrieval: RetrievalResult,
    ) -> QasperGeneratedAnswer | str: ...


@dataclass(frozen=True, slots=True)
class QasperBenchmarkRunResult:
    run_id: str
    run_directory: Path
    manifest_path: Path
    predictions_path: Path
    retrieval_trace_path: Path
    metrics_path: Path
    errors_path: Path
    qrels_path: Path
    question_count: int
    error_count: int
    run_status: str


@dataclass(frozen=True, slots=True)
class QasperAblationSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    status: str


@dataclass(frozen=True, slots=True)
class QasperRaptorAblationSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    tree_count: int
    status: str


@dataclass(frozen=True, slots=True)
class QasperEvidenceSelectionSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    status: str


@dataclass(frozen=True, slots=True)
class QasperAdaptiveRetrievalSuiteResult:
    suite_id: str
    suite_directory: Path
    manifest_path: Path
    comparison_path: Path
    variant_count: int
    status: str


class _GroundedChatAdapter:
    def __init__(self, chat_service: AIChatService) -> None:
        self._chat_service = chat_service

    def send(self, **kwargs: Any) -> Any:
        request = ChatRequest(
            session_id=str(kwargs.get("session_id", "qasper") or "qasper"),
            user_message=str(kwargs.get("user_message", "") or ""),
            context=ChatContext(),
            tool_name=str(kwargs.get("tool_name", "search_knowledge_base") or ""),
            tool_context=str(kwargs.get("tool_context", "") or ""),
        )
        return self._chat_service.execute(request)


class GroundedQasperAnswerer:
    """Generate answers through AITrans chat and grounded synthesis services."""

    def __init__(self, text_service: Any | None = None) -> None:
        self._text_service = text_service or LLMGateway().create_text_service(
            "agent_synthesis"
        )
        self._chat_service = AIChatService(self._text_service)
        self._grounded = GroundedSynthesisService(
            chat_service=_GroundedChatAdapter(self._chat_service)
        )

    @property
    def provider(self) -> str:
        return str(getattr(self._text_service, "provider_name", "") or "")

    @property
    def model(self) -> str:
        return str(getattr(self._text_service, "model", "") or "")

    def __call__(
        self,
        question: QasperQuestion,
        retrieval: RetrievalResult,
    ) -> QasperGeneratedAnswer:
        evidence = build_agent_evidence(retrieval)
        if not evidence:
            return QasperGeneratedAnswer(
                answer="Unanswerable",
                provider="policy",
                model="insufficient-evidence",
                metadata={"abstained": True, "reason": "no_retrieved_evidence"},
            )
        citations = build_evidence_citations(evidence)
        context_overrides = _supplemental_context_overrides(retrieval)
        started = perf_counter()
        result = self._grounded.send_verified(
            evidence=evidence,
            citations=citations,
            context_overrides=context_overrides,
            session_id=f"qasper-{question.question_id}",
            user_message=question.question,
        )
        return QasperGeneratedAnswer(
            answer=result.answer.output_text,
            provider=result.answer.provider or self.provider,
            model=result.answer.model or self.model,
            latency_ms=(perf_counter() - started) * 1000,
            metadata={
                "fallback_applied": result.fallback_applied,
                "partial_grounding": result.partial_grounding,
                "verification_passed": (
                    bool(result.verification.passed)
                    if result.verification is not None
                    else None
                ),
                "claim_count": (
                    int(result.verification.claim_count)
                    if result.verification is not None
                    else 0
                ),
                "unsupported_claim_count": (
                    int(result.verification.unsupported_claim_count)
                    if result.verification is not None
                    else 0
                ),
                "unsupported_claim_rate": (
                    result.verification.unsupported_claim_count
                    / result.verification.claim_count
                    if result.verification is not None
                    and result.verification.claim_count > 0
                    else None
                ),
            },
        )

    def close(self) -> None:
        close = getattr(self._text_service, "close", None)
        if callable(close):
            close()


def _answer_fields(question: QasperQuestion, aligned: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "question_id": question.question_id,
        "paper_id": question.paper_id,
        "question": question.question,
        "expected_retrieval": True,
        "no_answer": bool(question.answers)
        and all(answer.unanswerable for answer in question.answers),
        "answers": [
            {
                "annotation_id": answer.annotation_id,
                "answer_type": answer.answer_type,
                "answer": answer.answer_text,
                "extractive_spans": list(answer.extractive_spans),
                "free_form_answer": answer.free_form_answer,
                "yes_no": answer.yes_no,
                "evidence_texts": list(answer.evidence_texts),
                "highlighted_evidence": list(answer.highlighted_evidence),
                "evidence_paragraph_ids": list(item.paragraph_ids),
                "evidence_complete": item.evidence_complete,
            }
            for answer, item in zip(question.answers, aligned, strict=True)
        ],
        "gold_evidence_paragraph_ids": sorted(
            {
                paragraph_id
                for item in aligned
                for paragraph_id in item.paragraph_ids
            }
        ),
    }


def _source_paragraph_ids(chunk: Any) -> list[str]:
    benchmark = chunk.metadata.get("benchmark", {})
    paragraph_ids = (
        benchmark.get("source_paragraph_ids", [])
        if isinstance(benchmark, dict)
        else []
    )
    return [item for item in paragraph_ids if isinstance(item, str)]


def _candidate_context_chunks(candidate: Any) -> list[Any]:
    context_window = candidate.context_window
    if context_window is not None and context_window.chunks:
        return context_window.chunks
    return [candidate.chunk]


def _supplemental_context_overrides(retrieval: RetrievalResult) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for candidate in retrieval.candidates:
        window = candidate.context_window
        if window is None:
            continue
        supplemental: list[str] = []
        for chunk in window.chunks:
            if chunk.chunk_id == candidate.chunk.chunk_id:
                continue
            location = " / ".join(chunk.section_path) or chunk.section_heading or "same section"
            supplemental.append(f"[Supplemental {location}]\n{chunk.text.strip()}")
        text = "\n\n".join(item for item in supplemental if item.strip())
        if text:
            overrides[f"evidence:{candidate.chunk.chunk_id}"] = text
    return overrides


def _candidate_trace(candidate: Any) -> dict[str, Any]:
    chunk = candidate.chunk
    context_window = candidate.context_window
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "rank": candidate.rank,
        "text": chunk.text,
        "title": chunk.title,
        "token_count": chunk.token_count,
        "section_heading": chunk.section_heading,
        "section_path": chunk.section_path,
        "source_paragraph_ids": _source_paragraph_ids(chunk),
        "scores": {
            "dense": candidate.dense_score,
            "sparse": candidate.sparse_score,
            "fusion": candidate.fusion_score,
            "rerank": candidate.rerank_score,
        },
        "metadata": candidate.metadata,
        "context_window": (
            {
                "anchor_chunk_id": context_window.anchor_chunk_id,
                "chunk_ids": [item.chunk_id for item in context_window.chunks],
                "source_paragraph_ids": list(
                    dict.fromkeys(
                        paragraph_id
                        for context_chunk in context_window.chunks
                        for paragraph_id in _source_paragraph_ids(context_chunk)
                    )
                ),
                "text": context_window.text,
                "token_count": context_window.token_count,
            }
            if context_window is not None
            else None
        ),
    }


_RETRIEVAL_COMPONENTS = (
    "query_planning_ms",
    "embedding_ms",
    "dense_search_ms",
    "sparse_search_ms",
    "structural_search_ms",
    "fusion_ms",
    "rerank_ms",
    "small_to_big_ms",
)
_RETRIEVAL_STAGE_IDS = (
    "dense_chunk_ids",
    "sparse_chunk_ids",
    "structural_chunk_ids",
    "pre_rerank_chunk_ids",
)


def _identity_query_plan(query: str) -> RagQueryPlan:
    return RagQueryPlan(original_query=query, rewritten_query=query, subqueries=[])


def _raptor_summary_candidates(
    hits: Sequence[RaptorSearchHit],
    *,
    index: Any,
) -> list[RetrievalCandidate]:
    candidates: list[RetrievalCandidate] = []
    seen_chunk_ids: set[str] = set()
    for hit in hits:
        for chunk_id in hit.node.descendant_chunk_ids:
            if chunk_id in seen_chunk_ids:
                continue
            chunk = index.runtime.sparse_retriever.get_chunk(chunk_id)
            if chunk is None:
                continue
            seen_chunk_ids.add(chunk_id)
            candidates.append(
                RetrievalCandidate(
                    chunk=chunk,
                    fusion_score=hit.score,
                    rank=len(candidates) + 1,
                    metadata={
                        "raptor_summary_node_id": hit.node.node_id,
                        "raptor_summary_level": hit.node.level,
                        "raptor_summary_score": hit.score,
                    },
                )
            )
    return candidates


def _raptor_hit_trace(hits: Sequence[RaptorSearchHit]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": hit.node.node_id,
            "level": hit.node.level,
            "score": hit.score,
            "descendant_chunk_count": len(hit.node.descendant_chunk_ids),
            "descendant_paragraph_ids": list(hit.node.descendant_paragraph_ids),
        }
        for hit in hits
    ]


def _retrieve_raptor_question(
    query: str,
    *,
    index: Any,
    document_id: str,
    tree: RaptorTree,
    variant: str,
) -> tuple[RetrievalResult, dict[str, Any]]:
    if variant not in {"R0", "R1", "R2", "R3"}:
        raise ValueError("RAPTOR variant must be R0, R1, R2, or R3")
    started = perf_counter()
    filters = VectorSearchFilter(document_ids=[document_id])
    summary_hits: list[RaptorSearchHit] = []
    summary_search_ms = 0.0
    fallback_reason = ""

    if variant == "R0":
        intent = detect_structural_intent(query)
        result = index.runtime.retrieval_service.retrieve(
            query,
            filters=filters,
            section_hints=intent.section_aliases,
            final_top_k=BENCHMARK_FINAL_TOP_K,
            dense_enabled=True,
            sparse_enabled=True,
            structural_enabled=True,
            reranker_enabled=True,
            small_to_big_enabled=False,
        )
        candidates = result.candidates
        strategy = "flat-structural"
    else:
        query_vector = index.runtime.embedding_provider.embed_query(query)
        summary_started = perf_counter()
        summary_hits = rank_summary_nodes(query_vector, tree, top_k=8)
        summary_search_ms = (perf_counter() - summary_started) * 1000
        summary_candidates = _raptor_summary_candidates(summary_hits, index=index)

        if variant == "R1":
            leaf_candidates = index.runtime.vector_store.search(
                query_vector,
                top_k=BENCHMARK_FINAL_TOP_K,
                filters=filters,
            )
            candidates = rrf_fuse(
                [leaf_candidates, summary_candidates],
                limit=BENCHMARK_FINAL_TOP_K,
            )
            strategy = "raptor-mixed-leaf-summary"
        elif variant == "R2":
            candidates = rrf_fuse(
                [summary_candidates],
                limit=BENCHMARK_FINAL_TOP_K,
            )
            strategy = "raptor-collapsed-summary"
        else:
            base_result = index.runtime.retrieval_service.retrieve(
                query,
                filters=filters,
                final_top_k=BENCHMARK_FINAL_TOP_K,
                dense_enabled=True,
                sparse_enabled=True,
                structural_enabled=False,
                reranker_enabled=False,
                small_to_big_enabled=False,
            )
            candidates = rrf_fuse(
                [base_result.candidates, summary_candidates],
                limit=max(BENCHMARK_FINAL_TOP_K, index.runtime.config.retrieval.fusion_top_k),
            )
            try:
                candidates = index.runtime.reranker.rerank(
                    query,
                    candidates,
                    top_k=min(BENCHMARK_FINAL_TOP_K, len(candidates)),
                )
            except Exception as exc:  # noqa: BLE001 - retain fused RAPTOR candidates
                fallback_reason = str(exc) or exc.__class__.__name__
            strategy = "raptor-hybrid-rerank"

        if variant != "R2" and not candidates:
            fallback_reason = fallback_reason or "empty_raptor_candidate_pool"

        result = RetrievalResult(
            query=query,
            candidates=candidates,
            retrieval_strategy=strategy,
            elapsed_ms=(perf_counter() - started) * 1000,
            metadata={},
        )

    total_ms = (perf_counter() - started) * 1000
    result.metadata.update(
        {
            "raptor_variant": variant,
            "raptor_tree_fingerprint": tree.fingerprint,
            "raptor_tree_cache_hit": tree.cache_hit,
            "raptor_summary_node_count": len(tree.nodes),
            "raptor_summary_search_ms": summary_search_ms,
            "raptor_summary_hits": _raptor_hit_trace(summary_hits),
            "raptor_fallback_reason": fallback_reason,
            "query_planning_ms": 0.0,
        }
    )
    result.elapsed_ms = total_ms
    source_paragraph_ids = list(
        dict.fromkeys(
            paragraph_id
            for candidate in result.candidates
            for context_chunk in _candidate_context_chunks(candidate)
            for paragraph_id in _source_paragraph_ids(context_chunk)
        )
    )
    round_trace = {
        "round": 1,
        "query": query,
        "latency_ms": total_ms,
        "candidate_chunk_ids": [item.chunk.chunk_id for item in result.candidates],
        "source_paragraph_ids": source_paragraph_ids,
        "context_evidence_paragraph_ids": source_paragraph_ids,
        "context_token_count": sum(item.chunk.token_count for item in result.candidates),
        "new_chunk_count": len(result.candidates),
        "raptor_summary_hits": _raptor_hit_trace(summary_hits),
    }
    return result, round_trace


def _raptor_question_category(
    *,
    question: QasperQuestion,
    paper: Any,
    aligned_answers: Sequence[Any],
) -> str:
    section_by_paragraph = {
        paragraph.paragraph_id: paragraph.section_index
        for paragraph in paper.paragraphs
    }
    breadth = max(
        (
            len(
                {
                    section_by_paragraph[paragraph_id]
                    for paragraph_id in answer.paragraph_ids
                    if paragraph_id in section_by_paragraph
                }
            )
            for answer in aligned_answers
            if answer.paragraph_ids and answer.evidence_complete
        ),
        default=0,
    )
    if not breadth:
        if all(answer.unanswerable for answer in question.answers):
            return "unanswerable"
        return "unclassified"
    if breadth == 1:
        return "local"
    if breadth == 2:
        return "cross_section"
    return "global"


def _aggregate_retrievals(
    original_query: str,
    retrievals: list[RetrievalResult],
) -> RetrievalResult:
    if not retrievals:
        raise ValueError("at least one successful retrieval is required")
    if len(retrievals) == 1:
        merged = retrievals[0]
    else:
        merged = merge_query_results(
            original_query,
            retrievals,
            limit=BENCHMARK_FINAL_TOP_K,
        )

    metadata = dict(merged.metadata)
    for key in _RETRIEVAL_COMPONENTS:
        metadata[key] = sum(float(item.metadata.get(key, 0.0) or 0.0) for item in retrievals)
    for key in _RETRIEVAL_STAGE_IDS:
        metadata[key] = list(
            dict.fromkeys(
                chunk_id
                for item in retrievals
                for chunk_id in item.metadata.get(key, [])
                if isinstance(chunk_id, str) and chunk_id
            )
        )
    for key in ("dense_count", "sparse_count", "structural_count"):
        metadata[key] = sum(int(item.metadata.get(key, 0) or 0) for item in retrievals)
    metadata.update(
        {
            "query_count": len(retrievals),
            "retrieval_queries": [item.query for item in retrievals],
            "fusion_count": len(
                {
                    candidate.chunk.chunk_id
                    for item in retrievals
                    for candidate in item.candidates
                }
            ),
            "final_count": len(merged.candidates),
            "reranker_applied": any(
                bool(item.metadata.get("reranker_applied")) for item in retrievals
            ),
            "reranker_enabled": any(
                bool(item.metadata.get("reranker_enabled")) for item in retrievals
            ),
            "small_to_big_enabled": any(
                bool(item.metadata.get("small_to_big_enabled")) for item in retrievals
            ),
        }
    )
    return merged.model_copy(
        update={
            "query": original_query,
            "metadata": metadata,
        }
    )


def _gate_evidence(retrieval: RetrievalResult) -> list[AgentEvidenceItem]:
    items: list[AgentEvidenceItem] = []
    for candidate in retrieval.candidates:
        chunk = candidate.chunk
        score = (
            candidate.rerank_score
            if candidate.rerank_score is not None
            else candidate.fusion_score
        )
        items.append(
            AgentEvidenceItem(
                evidence_id=chunk.chunk_id,
                source_type="qasper_paper",
                source_id=chunk.document_id,
                title=chunk.title,
                location=" / ".join(chunk.section_path) or chunk.section_heading,
                excerpt=chunk.text,
                score=score,
                metadata={"source_paragraph_ids": _source_paragraph_ids(chunk)},
            )
        )
    return items


def _retrieve_variant_question(
    question: QasperQuestion,
    *,
    index: Any,
    document_id: str,
    variant: QasperAblationVariant,
    query_planner: Any | None,
) -> tuple[
    RetrievalResult,
    RagQueryPlan,
    list[dict[str, Any]],
    dict[str, Any] | None,
    float,
]:
    planning_started = perf_counter()
    plan = (
        query_planner.plan(question.question)
        if variant.multi_query and query_planner is not None
        else _identity_query_plan(question.question)
    )
    planning_ms = (perf_counter() - planning_started) * 1000
    retrieval_queries = list(plan.retrieval_queries) if variant.multi_query else [question.question]
    if variant.evidence_gate and len(retrieval_queries) < 2:
        follow_up_query = f"{question.question} supporting evidence"
        if follow_up_query.casefold() not in {item.casefold() for item in retrieval_queries}:
            retrieval_queries.append(follow_up_query)
    gate = AgentEvidenceGateService() if variant.evidence_gate else None
    successful_retrievals: list[RetrievalResult] = []
    round_traces: list[dict[str, Any]] = []
    last_gate: dict[str, Any] | None = None
    previous_chunk_ids: set[str] = set()

    for round_number, retrieval_query in enumerate(retrieval_queries[:3], start=1):
        intent = detect_structural_intent(retrieval_query) if variant.structural else None
        section_hints = intent.section_aliases if intent is not None else ()
        started = perf_counter()
        result = index.runtime.retrieval_service.retrieve(
            retrieval_query,
            filters=VectorSearchFilter(document_ids=[document_id]),
            section_hints=section_hints,
            final_top_k=BENCHMARK_FINAL_TOP_K,
            dense_enabled=variant.dense,
            sparse_enabled=variant.sparse,
            structural_enabled=variant.structural,
            reranker_enabled=variant.reranker,
            small_to_big_enabled=variant.small_to_big,
        )
        round_latency_ms = (perf_counter() - started) * 1000
        returned_document_ids = {item.chunk.document_id for item in result.candidates}
        if returned_document_ids.difference({document_id}):
            raise RuntimeError("known-paper retrieval returned a chunk from another paper")
        successful_retrievals.append(result)
        new_chunk_ids = {
            candidate.chunk.chunk_id for candidate in result.candidates
        }.difference(previous_chunk_ids)
        previous_chunk_ids.update(candidate.chunk.chunk_id for candidate in result.candidates)
        round_trace: dict[str, Any] = {
            "round": round_number,
            "query": retrieval_query,
            "latency_ms": round_latency_ms,
            "candidate_chunk_ids": [item.chunk.chunk_id for item in result.candidates],
            "source_paragraph_ids": list(
                dict.fromkeys(
                    paragraph_id
                    for item in result.candidates
                    for paragraph_id in _source_paragraph_ids(item.chunk)
                )
            ),
            "context_evidence_paragraph_ids": list(
                dict.fromkeys(
                    paragraph_id
                    for item in result.candidates
                    for context_chunk in _candidate_context_chunks(item)
                    for paragraph_id in _source_paragraph_ids(context_chunk)
                )
            ),
            "context_token_count": sum(
                item.context_window.token_count
                if item.context_window is not None
                else item.chunk.token_count
                for item in result.candidates
            ),
            "new_chunk_count": len(new_chunk_ids),
        }
        if gate is not None:
            cumulative = _aggregate_retrievals(question.question, successful_retrievals)
            assessment = gate.assess(
                evidence=_gate_evidence(cumulative),
                latest_retrieval=AgentRetrievalObservation(
                    query=retrieval_query,
                    retrieval_strategy=result.retrieval_strategy,
                    result_count=len(result.candidates),
                    evidence_count=len(cumulative.candidates),
                    novel_evidence_count=min(len(new_chunk_ids), len(cumulative.candidates)),
                    fallback_reason=str(result.metadata.get("fallback_reason", "") or ""),
                ),
                search_count=round_number,
                remaining_searches=max(0, min(3, len(retrieval_queries)) - round_number),
            )
            gate_sufficient = (
                assessment.action == "stop"
                and "evidence_sufficient" in assessment.reason_codes
            )
            last_gate = {
                "sufficient": gate_sufficient,
                "action": assessment.action,
                "reason_codes": list(assessment.reason_codes),
                "evidence_count": assessment.evidence_count,
                "quality_score": assessment.quality_score,
                "search_count": assessment.search_count,
                "remaining_searches": assessment.remaining_searches,
            }
            round_trace["gate"] = last_gate
        round_traces.append(round_trace)
        if gate is not None and last_gate and last_gate["action"] == "stop":
            break

    return (
        _aggregate_retrievals(question.question, successful_retrievals),
        plan,
        round_traces,
        last_gate,
        planning_ms,
    )


def _evidence_selection_ablation_variant(
    variant_id: str,
) -> QasperAblationVariant:
    reranker_enabled = variant_id != "raw_top_k"
    names = {
        "raw_top_k": "Raw Top-K",
        "rerank_top_k": "Rerank Top-K",
        "evidence_selection": "Evidence Selection",
    }
    return QasperAblationVariant(
        variant_id=f"ES_{variant_id.upper()}",
        name=names[variant_id],
        dense=True,
        sparse=True,
        reranker=reranker_enabled,
        structural=False,
        small_to_big=False,
        multi_query=False,
        evidence_gate=False,
    )


def _normalize_evidence_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _map_selected_excerpt_to_paragraphs(
    candidate: RetrievalCandidate,
    *,
    paper: Any,
) -> tuple[list[str], list[str]]:
    benchmark_metadata = candidate.chunk.metadata.get("benchmark", {})
    source_ids = (
        benchmark_metadata.get("source_paragraph_ids", [])
        if isinstance(benchmark_metadata, dict)
        else []
    )
    source_ids = [value for value in source_ids if isinstance(value, str)]
    excerpt = _normalize_evidence_text(candidate.chunk.text)
    matched_ids = [
        paragraph.paragraph_id
        for paragraph in paper.paragraphs
        if paragraph.paragraph_id in source_ids
        and excerpt
        and excerpt in _normalize_evidence_text(paragraph.text)
    ]
    return list(dict.fromkeys(source_ids)), list(dict.fromkeys(matched_ids))


def _retain_only_excerpt_paragraphs(
    candidates: Sequence[RetrievalCandidate],
    *,
    paper: Any,
) -> list[RetrievalCandidate]:
    mapped: list[RetrievalCandidate] = []
    for candidate in candidates:
        original_ids, matched_ids = _map_selected_excerpt_to_paragraphs(
            candidate,
            paper=paper,
        )
        chunk_metadata = dict(candidate.chunk.metadata)
        benchmark_metadata = dict(chunk_metadata.get("benchmark", {}))
        benchmark_metadata["source_paragraph_ids"] = matched_ids
        chunk_metadata["benchmark"] = benchmark_metadata
        candidate_metadata = dict(candidate.metadata)
        selection_metadata = dict(candidate_metadata.get("evidence_selection", {}))
        selection_metadata["source_paragraph_ids"] = original_ids
        selection_metadata["matched_paragraph_ids"] = matched_ids
        candidate_metadata["evidence_selection"] = selection_metadata
        mapped.append(
            candidate.model_copy(
                update={
                    "chunk": candidate.chunk.model_copy(
                        update={"metadata": chunk_metadata}
                    ),
                    "metadata": candidate_metadata,
                }
            )
        )
    return mapped


def _evidence_selection_round(
    *,
    query: str,
    retrieval: RetrievalResult,
    latency_ms: float,
) -> dict[str, Any]:
    candidates = retrieval.candidates
    paragraph_ids = list(
        dict.fromkeys(
            paragraph_id
            for candidate in candidates
            for paragraph_id in _source_paragraph_ids(candidate.chunk)
        )
    )
    selection = retrieval.metadata.get("evidence_selection", {})
    return {
        "round": 1,
        "query": query,
        "latency_ms": latency_ms,
        "candidate_chunk_ids": [item.chunk.chunk_id for item in candidates],
        "source_paragraph_ids": paragraph_ids,
        "context_evidence_paragraph_ids": paragraph_ids,
        "context_token_count": sum(item.chunk.token_count for item in candidates),
        "new_chunk_count": len(candidates),
        "evidence_selection": selection,
    }


def _adaptive_ablation_variant(variant_id: str) -> QasperAblationVariant:
    names = {
        "one_shot": "One-shot hybrid retrieval",
        "multi_query": "Multi-query hybrid retrieval",
        "evidence_gated": "Evidence-gated re-retrieval",
        "requirement_aware": "Requirement-aware re-retrieval",
    }
    return QasperAblationVariant(
        variant_id=f"AR_{variant_id.upper()}",
        name=names[variant_id],
        dense=True,
        sparse=True,
        reranker=True,
        structural=False,
        small_to_big=False,
        multi_query=variant_id in {"multi_query", "evidence_gated"},
        evidence_gate=variant_id == "evidence_gated",
    )


def _retrieve_requirement_aware_question(
    question: QasperQuestion,
    *,
    index: Any,
    document_id: str,
    maximum_rounds: int = 3,
) -> tuple[RetrievalResult, list[dict[str, Any]], tuple[EvidenceRequirement, ...]]:
    requirements = infer_evidence_requirements(question.question)
    retrievals: list[RetrievalResult] = []
    round_traces: list[dict[str, Any]] = []
    attempted_requirement_ids: set[str] = set()
    for round_number in range(1, maximum_rounds + 1):
        if not retrievals:
            retrieval_query = question.question
        else:
            missing = next(
                (
                    item
                    for item in requirements
                    if item.status == "missing"
                    and item.id not in attempted_requirement_ids
                ),
                None,
            )
            if missing is None:
                break
            attempted_requirement_ids.add(missing.id)
            retrieval_query = missing.query
        started = perf_counter()
        result = index.runtime.retrieval_service.retrieve(
            retrieval_query,
            filters=VectorSearchFilter(document_ids=[document_id]),
            final_top_k=BENCHMARK_FINAL_TOP_K,
            dense_enabled=True,
            sparse_enabled=True,
            structural_enabled=False,
            reranker_enabled=True,
            small_to_big_enabled=False,
        )
        round_latency_ms = (perf_counter() - started) * 1000
        returned_document_ids = {item.chunk.document_id for item in result.candidates}
        if returned_document_ids.difference({document_id}):
            raise RuntimeError("known-paper retrieval returned a chunk from another paper")
        retrievals.append(result)
        cumulative = _aggregate_retrievals(question.question, retrievals)
        requirements = assess_evidence_requirements(
            requirements,
            cumulative.candidates,
        )
        context_paragraph_ids = list(
            dict.fromkeys(
                paragraph_id
                for candidate in cumulative.candidates
                for paragraph_id in _source_paragraph_ids(candidate.chunk)
            )
        )
        round_traces.append(
            {
                "round": round_number,
                "query": retrieval_query,
                "latency_ms": round_latency_ms,
                "candidate_chunk_ids": [
                    item.chunk.chunk_id for item in result.candidates
                ],
                "source_paragraph_ids": list(
                    dict.fromkeys(
                        paragraph_id
                        for candidate in result.candidates
                        for paragraph_id in _source_paragraph_ids(candidate.chunk)
                    )
                ),
                "context_evidence_paragraph_ids": context_paragraph_ids,
                "context_token_count": sum(
                    item.context_window.token_count
                    if item.context_window is not None
                    else item.chunk.token_count
                    for item in cumulative.candidates
                ),
                "new_chunk_count": len(result.candidates),
                "evidence_requirements": [item.as_dict() for item in requirements],
                "requirement_coverage": evidence_requirement_coverage(requirements),
                "missing_requirement_ids": [
                    item.id for item in requirements if item.status == "missing"
                ],
            }
        )
        if not any(item.status == "missing" for item in requirements):
            break

    merged = _aggregate_retrievals(question.question, retrievals)
    merged.metadata.update(
        {
            "adaptive_variant": "requirement_aware",
            "evidence_requirements": [item.as_dict() for item in requirements],
            "requirement_coverage": evidence_requirement_coverage(requirements),
            "requirement_round_count": len(retrievals),
            "requirement_retrieval_queries": [item.query for item in retrievals],
        }
    )
    return merged, round_traces, requirements


def _new_run_id(split: str, mode: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"qasper-{split}-{mode}-{stamp}-{uuid.uuid4().hex[:8]}"


def run_qasper_benchmark(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    embedding_provider: Any | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    query_planner: Any | None = None,
    variant: QasperAblationVariant | str | None = None,
    raptor_variant: str | None = None,
    raptor_trees: Mapping[str, RaptorTree] | None = None,
    evidence_selection_variant: str | None = None,
    evidence_selector: EvidenceSelectionService | None = None,
    adaptive_variant: str | None = None,
    run_id: str | None = None,
    rebuild_index: bool = False,
) -> QasperBenchmarkRunResult:
    """Run the current AITrans RAG path with strict known-paper scoping."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    if limit is None:
        limit = RUN_LIMITS[normalized_mode]
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    selected = sample_qasper_dataset(dataset, limit=limit, seed=seed)
    normalized_evidence_selection_variant = (
        str(evidence_selection_variant).strip().casefold()
        if evidence_selection_variant is not None
        else None
    )
    if normalized_evidence_selection_variant is not None and normalized_evidence_selection_variant not in {
        "raw_top_k",
        "rerank_top_k",
        "evidence_selection",
    }:
        raise ValueError(
            "evidence_selection_variant must be raw_top_k, rerank_top_k, or evidence_selection"
        )
    normalized_adaptive_variant = (
        str(adaptive_variant).strip().casefold()
        if adaptive_variant is not None
        else None
    )
    if normalized_adaptive_variant is not None and normalized_adaptive_variant not in {
        "one_shot",
        "multi_query",
        "evidence_gated",
        "requirement_aware",
    }:
        raise ValueError(
            "adaptive_variant must be one_shot, multi_query, evidence_gated, or requirement_aware"
        )
    if (
        normalized_evidence_selection_variant is not None
        and normalized_adaptive_variant is not None
    ):
        raise ValueError("evidence-selection and adaptive variants cannot be combined")
    selected_variant = (
        _evidence_selection_ablation_variant(normalized_evidence_selection_variant)
        if normalized_evidence_selection_variant is not None
        else (
            _adaptive_ablation_variant(normalized_adaptive_variant)
            if normalized_adaptive_variant is not None
            else get_qasper_ablation_variant(variant)
        )
    )
    normalized_raptor_variant = (
        str(raptor_variant).strip().upper() if raptor_variant is not None else None
    )
    if normalized_raptor_variant is not None and normalized_raptor_variant not in {
        "R0",
        "R1",
        "R2",
        "R3",
    }:
        raise ValueError("raptor_variant must be one of R0, R1, R2, or R3")
    if normalized_raptor_variant is not None and raptor_trees is None:
        raise ValueError("raptor_trees are required for a RAPTOR benchmark run")
    benchmark_directory = benchmark_root(root)
    selected_run_id = run_id or _new_run_id(selected.split, normalized_mode)
    if not _RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id may contain only letters, digits, dots, underscores, and hyphens")
    run_directory = benchmark_directory / "results" / selected_run_id
    if run_directory.exists():
        raise FileExistsError(f"QASPER run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = run_directory / "manifest.json"
    predictions_path = run_directory / "predictions.jsonl"
    trace_path = run_directory / "retrieval_trace.jsonl"
    metrics_path = run_directory / "metrics.json"
    errors_path = run_directory / "errors.jsonl"
    for output_path in (predictions_path, trace_path, errors_path):
        output_path.touch(exist_ok=False)
    started_at = datetime.now(UTC)
    alignment = align_qasper_evidence(selected)
    sample_hash = qasper_sample_hash(selected)
    qrels_path = benchmark_directory / "qrels" / f"{sample_hash}.jsonl"
    qrels_records = [
        _answer_fields(question, alignment.by_question[question.question_id])
        for question in selected.questions
    ]
    atomic_write_jsonl(qrels_path, qrels_records)
    source_config = (config or RagConfig()).model_copy(deep=True)
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "run_id": selected_run_id,
        "status": "running",
        "dataset": "qasper",
        "dataset_version": selected.dataset_version,
        "split": selected.split,
        "source_path": selected.source_path,
        "source_sha256": selected.source_sha256,
        "sample_hash": sample_hash,
        "mode": normalized_mode,
        "limit": limit,
        "seed": seed,
        "question_count": len(selected.questions),
        "paper_count": len(selected.papers),
        "selected_question_ids": [question.question_id for question in selected.questions],
        "qrels_path": str(qrels_path),
        "started_at": started_at.isoformat(),
        "rag_config": source_config.model_dump(mode="json"),
        "answer_generation": answerer is not None,
        "ablation_variant": selected_variant.as_dict(),
        "evidence_selection_variant": normalized_evidence_selection_variant,
        "adaptive_variant": normalized_adaptive_variant,
        "evidence_selection_parameters": (
            {
                "candidate_pool_size": 20,
                "selected_top_k": 5,
                "maximum_excerpt_tokens": 180,
                "extractor_model": (
                    evidence_selector.extractor_model
                    if evidence_selector is not None
                    else "extractive-sentence-spans-v1"
                ),
                "prompt_version": (
                    evidence_selector.prompt_version
                    if evidence_selector is not None
                    else "extractive-sentence-spans-v1"
                ),
            }
            if normalized_evidence_selection_variant == "evidence_selection"
            else None
        ),
        "raptor_variant": normalized_raptor_variant,
        "raptor_tree_fingerprints": (
            {
                document_id: tree.fingerprint
                for document_id, tree in sorted(raptor_trees.items())
            }
            if raptor_trees is not None
            else {}
        ),
        "files": {
            "predictions": predictions_path.name,
            "retrieval_trace": trace_path.name,
            "metrics": metrics_path.name,
            "errors": errors_path.name,
        },
    }
    atomic_write_json(manifest_path, manifest)

    retrieval_latencies: list[float] = []
    answer_latencies: list[float] = []
    strategy_counts: dict[str, int] = {}
    error_count = 0
    succeeded_retrievals = 0
    answer_count = 0
    index = None
    active_evidence_selector = evidence_selector
    try:
        index = build_qasper_index(
            selected,
            storage_root=benchmark_directory,
            config=source_config,
            embedding_provider=embedding_provider,
            reranker=reranker,
            rebuild=rebuild_index,
        )
        if (
            normalized_evidence_selection_variant == "evidence_selection"
            and active_evidence_selector is None
        ):
            active_evidence_selector = EvidenceSelectionService(
                embedding_provider=index.runtime.embedding_provider
            )
        manifest["index"] = {
            "fingerprint": index.result.fingerprint,
            "fingerprint_inputs": index.result.fingerprint_inputs,
            "index_root": str(index.result.index_root),
            "cache_hit": index.result.cache_hit,
            "reused_paper_count": index.result.reused_paper_count,
            "indexed_paper_count": index.result.indexed_paper_count,
            "chunk_count": index.result.chunk_count,
        }
        manifest["embedding"] = {
            "provider": index.runtime.config.embedding.provider,
            "model": index.runtime.embedding_provider.model_name,
            "dimension": index.runtime.embedding_provider.dimension,
        }
        answer_provider = getattr(answerer, "provider", "") if answerer else ""
        answer_model = getattr(answerer, "model", "") if answerer else ""
        manifest["answer_model"] = {"provider": answer_provider, "model": answer_model}
        atomic_write_json(manifest_path, manifest)

        with (
            predictions_path.open("a", encoding="utf-8", newline="\n") as predictions_file,
            trace_path.open("a", encoding="utf-8", newline="\n") as trace_file,
            errors_path.open("a", encoding="utf-8", newline="\n") as errors_file,
        ):
            for question in selected.questions:
                retrieval_result: RetrievalResult | None = None
                predicted_answer = ""
                answer_info: dict[str, Any] = {}
                query_error = ""
                document_id = f"qasper:{selected.split}:{question.paper_id}"
                raptor_category = (
                    _raptor_question_category(
                        question=question,
                        paper=selected.papers[question.paper_id],
                        aligned_answers=alignment.by_question[question.question_id],
                    )
                    if normalized_raptor_variant is not None
                    else ""
                )
                retrieval_started = perf_counter()
                try:
                    if normalized_raptor_variant is not None:
                        tree = (raptor_trees or {}).get(document_id)
                        if tree is None:
                            raise ValueError(
                                f"RAPTOR tree is missing for {document_id!r}"
                            )
                        retrieval_result, raptor_round = _retrieve_raptor_question(
                            question.question,
                            index=index,
                            document_id=document_id,
                            tree=tree,
                            variant=normalized_raptor_variant,
                        )
                        query_plan = _identity_query_plan(question.question)
                        retrieval_rounds = [raptor_round]
                        sufficiency = None
                        query_planning_ms = 0.0
                    else:
                        if normalized_evidence_selection_variant is not None:
                            selection_enabled = (
                                normalized_evidence_selection_variant
                                == "evidence_selection"
                            )
                            retrieval_result = index.runtime.retrieval_service.retrieve(
                                question.question,
                                filters=VectorSearchFilter(document_ids=[document_id]),
                                final_top_k=20 if selection_enabled else 5,
                                dense_enabled=True,
                                sparse_enabled=True,
                                structural_enabled=False,
                                reranker_enabled=selected_variant.reranker,
                                small_to_big_enabled=False,
                            )
                            retrieval_pool_chunk_ids = [
                                item.chunk.chunk_id
                                for item in retrieval_result.candidates
                            ]
                            query_plan = _identity_query_plan(question.question)
                            query_planning_ms = 0.0
                            sufficiency = None
                            retrieval_rounds = []
                            if selection_enabled:
                                if active_evidence_selector is None:
                                    raise RuntimeError(
                                        "evidence selector was not initialized"
                                    )
                                selection_result = active_evidence_selector.select(
                                    question.question,
                                    retrieval_result.candidates,
                                    top_n=20,
                                    top_k=5,
                                )
                                selected_candidates = _retain_only_excerpt_paragraphs(
                                    [item.candidate for item in selection_result.selected],
                                    paper=selected.papers[question.paper_id],
                                )
                                selection_trace = selection_result.as_dict()
                                for trace_item, candidate in zip(
                                    selection_trace["selected"],
                                    selected_candidates,
                                    strict=True,
                                ):
                                    trace_item["matched_paragraph_ids"] = (
                                        _source_paragraph_ids(candidate.chunk)
                                    )
                                retrieval_result.candidates = selected_candidates
                                retrieval_result.metadata.update(
                                    {
                                        "evidence_selection": selection_trace,
                                        "evidence_extraction_ms": selection_result.extraction_ms,
                                        "evidence_scoring_ms": selection_result.scoring_ms,
                                        "evidence_extractor_invocations": (
                                            selection_result.candidate_pool_count
                                            if selection_result.extractor_model
                                            != "extractive-sentence-spans-v1"
                                            else 0
                                        ),
                                        "evidence_selection_pool_chunk_ids": retrieval_pool_chunk_ids,
                                    }
                                )
                            retrieval_rounds = [
                                _evidence_selection_round(
                                    query=question.question,
                                    retrieval=retrieval_result,
                                    latency_ms=retrieval_result.elapsed_ms,
                                )
                            ]
                        elif normalized_adaptive_variant == "requirement_aware":
                            (
                                retrieval_result,
                                retrieval_rounds,
                                _evidence_requirements,
                            ) = _retrieve_requirement_aware_question(
                                question,
                                index=index,
                                document_id=document_id,
                            )
                            query_plan = _identity_query_plan(question.question)
                            sufficiency = None
                            query_planning_ms = 0.0
                        else:
                            (
                                retrieval_result,
                                query_plan,
                                retrieval_rounds,
                                sufficiency,
                                query_planning_ms,
                            ) = _retrieve_variant_question(
                                question,
                                index=index,
                                document_id=document_id,
                                variant=selected_variant,
                                query_planner=query_planner,
                            )
                    retrieval_result.metadata["query_planning_ms"] = query_planning_ms
                    retrieval_ms = (perf_counter() - retrieval_started) * 1000
                    if normalized_evidence_selection_variant is not None:
                        retrieval_rounds[0]["latency_ms"] = retrieval_ms
                    retrieval_latencies.append(retrieval_ms)
                    strategy_counts[retrieval_result.retrieval_strategy] = (
                        strategy_counts.get(retrieval_result.retrieval_strategy, 0) + 1
                    )
                    succeeded_retrievals += 1
                except Exception as exc:  # noqa: BLE001 - record per-query failures
                    error_count += 1
                    query_error = str(exc) or exc.__class__.__name__
                    retrieval_ms = (perf_counter() - retrieval_started) * 1000
                    errors_file.write(
                        json.dumps(
                            {
                                "question_id": question.question_id,
                                "paper_id": question.paper_id,
                                "stage": "retrieval",
                                "error_type": exc.__class__.__name__,
                                "error": query_error,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    errors_file.flush()

                if retrieval_result is not None and answerer is not None:
                    answer_started = perf_counter()
                    try:
                        generated = answerer(question, retrieval_result)
                        measured_ms = (perf_counter() - answer_started) * 1000
                        if isinstance(generated, QasperGeneratedAnswer):
                            predicted_answer = generated.answer
                            answer_info = {
                                "provider": generated.provider,
                                "model": generated.model,
                                "latency_ms": generated.latency_ms or measured_ms,
                                "metadata": generated.metadata or {},
                            }
                            answer_latencies.append(float(answer_info["latency_ms"]))
                        else:
                            predicted_answer = str(generated)
                            answer_info = {"provider": answer_provider, "model": answer_model}
                            answer_latencies.append(measured_ms)
                        answer_count += 1
                    except Exception as exc:  # noqa: BLE001 - keep retrieval trace on LLM failure
                        error_count += 1
                        query_error = str(exc) or exc.__class__.__name__
                        answer_info = {
                            "error_type": exc.__class__.__name__,
                            "error": query_error,
                        }
                        errors_file.write(
                            json.dumps(
                                {
                                    "question_id": question.question_id,
                                    "paper_id": question.paper_id,
                                    "stage": "answer_generation",
                                    "error_type": exc.__class__.__name__,
                                    "error": query_error,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        errors_file.flush()

                prediction = {
                    "question_id": question.question_id,
                    "paper_id": question.paper_id,
                    "question": question.question,
                    "ablation_variant": selected_variant.variant_id,
                    "evidence_selection_variant": normalized_evidence_selection_variant,
                    "adaptive_variant": normalized_adaptive_variant,
                    "raptor_variant": normalized_raptor_variant,
                    "query_plan": (
                        query_plan.model_dump(mode="json")
                        if retrieval_result is not None
                        else None
                    ),
                    "query_planner_invoked": bool(
                        selected_variant.multi_query and query_planner is not None
                    ),
                    "answer": predicted_answer,
                    "answer_generation": answer_info,
                    "error": query_error,
                    "retrieved_chunk_ids": (
                        [item.chunk.chunk_id for item in retrieval_result.candidates]
                        if retrieval_result is not None
                        else []
                    ),
                    "predicted_evidence_paragraph_ids": (
                        list(
                            dict.fromkeys(
                                paragraph_id
                                for candidate in retrieval_result.candidates
                                for context_chunk in _candidate_context_chunks(candidate)
                                for paragraph_id in _source_paragraph_ids(context_chunk)
                            )
                        )
                        if retrieval_result is not None
                        else []
                    ),
                }
                evidence_paragraph_ids = prediction[
                    "predicted_evidence_paragraph_ids"
                ]
                paragraph_text_by_id = {
                    paragraph.paragraph_id: paragraph.text
                    for paragraph in selected.papers[question.paper_id].paragraphs
                }
                prediction["predicted_evidence"] = [
                    paragraph_text_by_id[paragraph_id]
                    for paragraph_id in evidence_paragraph_ids
                    if paragraph_id in paragraph_text_by_id
                ]
                trace = {
                    "question_id": question.question_id,
                    "paper_id": question.paper_id,
                    "query": question.question,
                    "scope_document_id": document_id,
                    "retrieval_strategy": (
                        retrieval_result.retrieval_strategy
                        if retrieval_result is not None
                        else "failed"
                    ),
                    "latency_ms": retrieval_ms,
                    "retrieval_metadata": (
                        retrieval_result.metadata if retrieval_result is not None else {}
                    ),
                    "stages": {
                        key: (retrieval_result.metadata.get(key, []) if retrieval_result else [])
                        for key in (
                            "dense_chunk_ids",
                            "sparse_chunk_ids",
                            "structural_chunk_ids",
                            "pre_rerank_chunk_ids",
                        )
                    },
                    "pre_rerank_candidates": (
                        [
                            {
                                "chunk_id": chunk_id,
                                "source_paragraph_ids": _source_paragraph_ids(
                                    index.runtime.sparse_retriever.get_chunk(chunk_id)
                                ),
                            }
                            for chunk_id in retrieval_result.metadata.get(
                                "pre_rerank_chunk_ids", []
                            )
                            if index.runtime.sparse_retriever.get_chunk(chunk_id)
                            is not None
                        ]
                        if retrieval_result is not None
                        else []
                    ),
                    "context_evidence_paragraph_ids": evidence_paragraph_ids,
                    "ablation_variant": selected_variant.as_dict(),
                    "evidence_selection_variant": normalized_evidence_selection_variant,
                    "adaptive_variant": normalized_adaptive_variant,
                    "raptor_variant": normalized_raptor_variant,
                    "raptor_category": raptor_category or None,
                    "query_plan": (
                        query_plan.model_dump(mode="json")
                        if retrieval_result is not None
                        else None
                    ),
                    "query_planner_invoked": bool(
                        selected_variant.multi_query and query_planner is not None
                    ),
                    "retrieval_rounds": (
                        retrieval_rounds if retrieval_result is not None else []
                    ),
                    "evidence_requirements": (
                        retrieval_result.metadata.get("evidence_requirements", [])
                        if retrieval_result is not None
                        else []
                    ),
                    "sufficiency": sufficiency if retrieval_result is not None else None,
                    **(
                        {"second_round": len(retrieval_rounds) > 1}
                        if (
                            selected_variant.evidence_gate
                            or normalized_adaptive_variant == "requirement_aware"
                        )
                        and retrieval_result is not None
                        else {}
                    ),
                    "final_candidates": (
                        [_candidate_trace(item) for item in retrieval_result.candidates]
                        if retrieval_result is not None
                        else []
                    ),
                    "answer": predicted_answer,
                    "answer_generation": answer_info,
                    "error": query_error,
                }
                predictions_file.write(
                    json.dumps(prediction, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                trace_file.write(
                    json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                predictions_file.flush()
                trace_file.flush()

        completed_at = datetime.now(UTC)
        run_status = "complete" if error_count == 0 else "partial"
        metrics = {
            "metric_version": 1,
            "status": "retrieval_complete" if answerer is None else "baseline_complete",
            "question_count": len(selected.questions),
            "retrieval_success_count": succeeded_retrievals,
            "answer_count": answer_count,
            "error_count": error_count,
            "retrieval_latency_ms": {
                "p50": round(percentile(retrieval_latencies, 50), 3),
                "p95": round(percentile(retrieval_latencies, 95), 3),
                "samples": len(retrieval_latencies),
            },
            "answer_latency_ms": {
                "p50": round(percentile(answer_latencies, 50), 3),
                "p95": round(percentile(answer_latencies, 95), 3),
                "samples": len(answer_latencies),
            },
            "retrieval_strategy_counts": dict(sorted(strategy_counts.items())),
        }
        atomic_write_json(metrics_path, metrics)
        manifest.update(
            {
                "status": run_status,
                "completed_at": completed_at.isoformat(),
                "elapsed_seconds": round((completed_at - started_at).total_seconds(), 3),
                "error_count": error_count,
                "retrieval_success_count": succeeded_retrievals,
                "answer_count": answer_count,
            }
        )
        atomic_write_json(manifest_path, manifest)
        return QasperBenchmarkRunResult(
            run_id=selected_run_id,
            run_directory=run_directory,
            manifest_path=manifest_path,
            predictions_path=predictions_path,
            retrieval_trace_path=trace_path,
            metrics_path=metrics_path,
            errors_path=errors_path,
            qrels_path=qrels_path,
            question_count=len(selected.questions),
            error_count=error_count,
            run_status=run_status,
        )
    except BaseException as exc:
        manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, manifest)
        with errors_path.open("a", encoding="utf-8", newline="\n") as errors_file:
            errors_file.write(
                json.dumps(
                    {
                        "stage": "index_or_runner",
                        "error_type": exc.__class__.__name__,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
        atomic_write_json(
            metrics_path,
            {
                "metric_version": 1,
                "status": "failed",
                "question_count": len(selected.questions),
                "error_count": error_count + 1,
            },
        )
        raise
    finally:
        if index is not None:
            index.close()


def run_qasper_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    variants: Sequence[QasperAblationVariant | str] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    query_planner: Any | None = None,
    suite_id: str | None = None,
) -> QasperAblationSuiteResult:
    """Run the query-time ablation matrix against one shared QASPER index."""

    benchmark_directory = benchmark_root(root)
    selected_variants = [
        get_qasper_ablation_variant(item)
        for item in (
            variants
            if variants is not None
            else [item.variant_id for item in QASPER_ABLATION_VARIANTS]
        )
    ]
    variant_ids = [item.variant_id for item in selected_variants]
    if not selected_variants:
        raise ValueError("at least one QASPER ablation variant is required")
    if len(set(variant_ids)) != len(variant_ids):
        raise ValueError("QASPER ablation variants must be unique")

    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )

    selected_suite_id = suite_id or _new_run_id(dataset.split, f"ablation-{mode}")
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "ablation" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "split": dataset.split,
        "mode": mode,
        "limit": limit if limit is not None else RUN_LIMITS.get(mode),
        "seed": seed,
        "index_rebuild": False,
        "status": "running",
        "variants": [item.as_dict() for item in selected_variants],
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    comparison_rows: list[dict[str, Any]] = []
    try:
        for variant in selected_variants:
            run_id = f"{selected_suite_id}-{variant.variant_id.lower()}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=mode,
                limit=limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                query_planner=query_planner,
                variant=variant,
                run_id=run_id,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant.variant_id,
                "name": variant.name,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "ai_trans_retrieval": metrics["ai_trans_retrieval"],
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "performance_ms": metrics["performance_ms"],
                "context_metrics": metrics.get("context_metrics", {}),
                "adaptive_retrieval": metrics.get("adaptive_retrieval", {}),
                "evidence_gate_evaluation": metrics.get("evidence_gate_evaluation", {}),
                "adaptive_metrics": metrics["adaptive_metrics"],
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant.variant_id,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "shared_index_fingerprint": "all variants use identical corpus/chunking/embedding fingerprint",
                "small_to_big_focus": [
                    "official Answer F1",
                    "official Evidence F1",
                    "Context Evidence Coverage",
                    "Context Tokens",
                ],
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_manifest.update(
            {
                "status": "complete",
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise

    return QasperAblationSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(comparison_rows),
        status="complete",
    )


def run_qasper_evidence_selection_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    variants: Sequence[str] = (
        "raw_top_k",
        "rerank_top_k",
        "evidence_selection",
    ),
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    excerpt_provider: EvidenceExcerptProvider | None = None,
    evidence_selector: EvidenceSelectionService | None = None,
    suite_id: str | None = None,
) -> QasperEvidenceSelectionSuiteResult:
    """Compare raw, reranked, and query-selected QASPER evidence on one index."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    selected_limit = RUN_LIMITS[normalized_mode] if limit is None else limit
    if selected_limit is not None and selected_limit <= 0:
        raise ValueError("limit must be positive")
    selected_variants = [str(value).strip().casefold() for value in variants]
    allowed_variants = {"raw_top_k", "rerank_top_k", "evidence_selection"}
    if not selected_variants:
        raise ValueError("at least one evidence-selection variant is required")
    if any(value not in allowed_variants for value in selected_variants):
        raise ValueError(
            "evidence-selection variants must be raw_top_k, rerank_top_k, or evidence_selection"
        )
    if len(set(selected_variants)) != len(selected_variants):
        raise ValueError("evidence-selection variants must be unique")

    benchmark_directory = benchmark_root(root)
    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )
    shared_selector = evidence_selector or EvidenceSelectionService(
        extractor=excerpt_provider,
        embedding_provider=shared_embedding,
    )

    selected_suite_id = suite_id or _new_run_id(
        dataset.split,
        f"evidence-selection-{normalized_mode}",
    )
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "evidence_selection" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "dataset_version": dataset.dataset_version,
        "split": dataset.split,
        "mode": normalized_mode,
        "limit": selected_limit,
        "seed": seed,
        "index_rebuild": False,
        "status": "running",
        "variants": selected_variants,
        "candidate_pool_size": 20,
        "selected_top_k": 5,
        "extractor_model": shared_selector.extractor_model,
        "prompt_version": shared_selector.prompt_version,
        "answer_generation": answerer is not None,
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    comparison_rows: list[dict[str, Any]] = []
    try:
        for variant_id in selected_variants:
            run_suffix = variant_id.replace("_", "-")
            run_id = f"{selected_suite_id[:100]}-es-{run_suffix}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=normalized_mode,
                limit=selected_limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                evidence_selection_variant=variant_id,
                evidence_selector=shared_selector,
                run_id=run_id,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant_id,
                "name": _evidence_selection_ablation_variant(variant_id).name,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "context_metrics": metrics.get("context_metrics", {}),
                "groundedness_metrics": metrics.get("groundedness_metrics", {}),
                "evidence_selection": metrics.get("evidence_selection", {}),
                "performance_ms": metrics.get("performance_ms", {}),
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant_id,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "shared_index_fingerprint": "all variants use identical corpus, chunking, and embedding configuration",
                "raw_top_k": "hybrid Dense + BM25 + RRF candidates, without reranking, final top 5",
                "rerank_top_k": "hybrid Dense + BM25 + RRF candidates, reranked, final top 5",
                "evidence_selection": "reranked top 20 chunks, exact query-conditioned evidence spans, then top 5 spans passed as grounded evidence",
                "metrics": [
                    "paragraph evidence precision, recall, and F1",
                    "official QASPER Answer F1 and Evidence F1",
                    "Context Tokens",
                    "Unsupported Claim Rate",
                    "evidence extraction and scoring latency",
                ],
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_status = (
            "complete"
            if all(row["run_status"] == "complete" for row in comparison_rows)
            else "partial"
        )
        suite_manifest.update(
            {
                "status": suite_status,
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise

    return QasperEvidenceSelectionSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(comparison_rows),
        status=suite_manifest["status"],
    )


def run_qasper_adaptive_retrieval_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    variants: Sequence[str] = (
        "one_shot",
        "multi_query",
        "evidence_gated",
        "requirement_aware",
    ),
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    answerer: QasperAnswerer | None = None,
    query_planner: Any | None = None,
    suite_id: str | None = None,
) -> QasperAdaptiveRetrievalSuiteResult:
    """Compare one-shot, multi-query, gate, and requirement-aware retrieval."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    selected_limit = RUN_LIMITS[normalized_mode] if limit is None else limit
    if selected_limit is not None and selected_limit <= 0:
        raise ValueError("limit must be positive")
    selected_variants = [str(value).strip().casefold() for value in variants]
    allowed_variants = {
        "one_shot",
        "multi_query",
        "evidence_gated",
        "requirement_aware",
    }
    if not selected_variants:
        raise ValueError("at least one adaptive-retrieval variant is required")
    if any(value not in allowed_variants for value in selected_variants):
        raise ValueError(
            "adaptive-retrieval variants must be one_shot, multi_query, evidence_gated, or requirement_aware"
        )
    if len(set(selected_variants)) != len(selected_variants):
        raise ValueError("adaptive-retrieval variants must be unique")
    if query_planner is None and set(selected_variants).intersection(
        {"multi_query", "evidence_gated"}
    ):
        raise ValueError(
            "a query_planner is required for multi_query and evidence_gated variants"
        )

    benchmark_directory = benchmark_root(root)
    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )
    selected_suite_id = suite_id or _new_run_id(
        dataset.split,
        f"adaptive-retrieval-{normalized_mode}",
    )
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "adaptive_retrieval" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "dataset_version": dataset.dataset_version,
        "split": dataset.split,
        "mode": normalized_mode,
        "limit": selected_limit,
        "seed": seed,
        "index_rebuild": False,
        "status": "running",
        "variants": selected_variants,
        "query_planner": type(query_planner).__name__ if query_planner else None,
        "requirement_max_retrieval_rounds": 3,
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    comparison_rows: list[dict[str, Any]] = []
    try:
        for variant_id in selected_variants:
            run_id = f"{selected_suite_id[:100]}-ar-{variant_id.replace('_', '-')}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=normalized_mode,
                limit=selected_limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                query_planner=query_planner,
                adaptive_variant=variant_id,
                run_id=run_id,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant_id,
                "name": _adaptive_ablation_variant(variant_id).name,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "performance_ms": metrics["performance_ms"],
                "context_metrics": metrics.get("context_metrics", {}),
                "adaptive_retrieval": metrics.get("adaptive_retrieval", {}),
                "evidence_gate_evaluation": metrics.get("evidence_gate_evaluation", {}),
                "evidence_requirement_evaluation": metrics.get(
                    "evidence_requirement_evaluation", {}
                ),
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant_id,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "shared_index_fingerprint": "all variants use identical corpus, chunking, and embedding configuration",
                "one_shot": "one hybrid Dense + BM25 + RRF retrieval followed by reranking",
                "multi_query": "bounded Query Planner rewrite and subqueries, fused through the existing retrieval merge",
                "evidence_gated": "multi-query retrieval with the existing evidence gate controlling bounded re-retrieval",
                "requirement_aware": "infer lightweight evidence requirements, assess lexical coverage, and re-retrieve only the first uncovered requirement for up to three total rounds",
                "requirement_coverage": "heuristic runtime coverage is reported separately from QASPER gold evidence recall",
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_status = (
            "complete"
            if all(row["run_status"] == "complete" for row in comparison_rows)
            else "partial"
        )
        suite_manifest.update(
            {
                "status": suite_status,
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise

    return QasperAdaptiveRetrievalSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(comparison_rows),
        status=suite_manifest["status"],
    )


def run_qasper_raptor_ablation(
    dataset: QasperDataset,
    *,
    root: str | Path | None = None,
    mode: str = "smoke",
    limit: int | None = None,
    seed: int = 42,
    config: RagConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Any | None = None,
    summary_provider: RaptorSummaryProvider | None = None,
    answerer: QasperAnswerer | None = None,
    variants: Sequence[str] = ("R0", "R1", "R2", "R3"),
    suite_id: str | None = None,
) -> QasperRaptorAblationSuiteResult:
    """Compare flat, mixed, collapsed, and hybrid RAPTOR retrieval variants."""

    normalized_mode = mode.strip().casefold()
    if normalized_mode not in RUN_LIMITS:
        raise ValueError(f"mode must be one of: {', '.join(RUN_LIMITS)}")
    selected_limit = RUN_LIMITS[normalized_mode] if limit is None else limit
    if selected_limit is not None and selected_limit <= 0:
        raise ValueError("limit must be positive")
    selected_dataset = sample_qasper_dataset(
        dataset,
        limit=selected_limit,
        seed=seed,
    )
    selected_variants = [str(value).strip().upper() for value in variants]
    if not selected_variants:
        raise ValueError("at least one RAPTOR variant is required")
    if any(value not in {"R0", "R1", "R2", "R3"} for value in selected_variants):
        raise ValueError("RAPTOR variants must be selected from R0, R1, R2, and R3")
    if len(set(selected_variants)) != len(selected_variants):
        raise ValueError("RAPTOR variants must be unique")

    benchmark_directory = benchmark_root(root)
    source_config = (config or RagConfig()).model_copy(deep=True)
    model_manager: ModelManager | None = None
    if embedding_provider is None or reranker is None:
        model_manager = ModelManager()
    shared_embedding = embedding_provider or create_embedding_provider(
        source_config.embedding,
        model_manager=model_manager,
    )
    shared_reranker = reranker or Qwen3RerankerProvider(
        source_config.reranker,
        model_manager=model_manager,
    )
    shared_summarizer = summary_provider or ExtractiveRaptorSummaryProvider()

    selected_suite_id = suite_id or _new_run_id(
        selected_dataset.split,
        f"raptor-{normalized_mode}",
    )
    if not _RUN_ID.fullmatch(selected_suite_id):
        raise ValueError("suite_id may contain only letters, digits, dots, underscores, and hyphens")
    suite_directory = benchmark_directory / "raptor" / "ablation" / selected_suite_id
    suite_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = suite_directory / "manifest.json"
    comparison_path = suite_directory / "comparison.json"
    suite_manifest: dict[str, Any] = {
        "manifest_version": 1,
        "suite_id": selected_suite_id,
        "dataset": "qasper",
        "dataset_version": selected_dataset.dataset_version,
        "split": selected_dataset.split,
        "mode": normalized_mode,
        "limit": selected_limit,
        "seed": seed,
        "status": "building_trees",
        "index_rebuild": False,
        "variants": selected_variants,
        "summary_model": shared_summarizer.model_name,
        "prompt_version": shared_summarizer.prompt_version,
        "tree_cache_parameters": {
            "branching_factor": 4,
            "clustering_version": "greedy-cosine-medoid-v1",
            "query_parameters_included": False,
        },
        "completed_runs": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(manifest_path, suite_manifest)

    index = None
    try:
        index = build_qasper_index(
            selected_dataset,
            storage_root=benchmark_directory,
            config=source_config,
            embedding_provider=shared_embedding,
            reranker=shared_reranker,
            rebuild=False,
        )
        chunks_by_document: dict[str, list[Any]] = {}
        expected_document_ids = {
            f"qasper:{selected_dataset.split}:{paper_id}"
            for paper_id in selected_dataset.papers
        }
        for chunk in index.runtime.sparse_retriever.list_chunks():
            if chunk.document_id in expected_document_ids:
                chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

        tree_builder = RaptorTreeBuilder(
            embedding_provider=index.runtime.embedding_provider,
            summary_provider=shared_summarizer,
            cache_directory=benchmark_directory / "raptor" / "trees",
            branching_factor=4,
        )
        trees: dict[str, RaptorTree] = {}
        tree_manifest: dict[str, Any] = {}
        for document_id in sorted(expected_document_ids):
            chunks = chunks_by_document.get(document_id, [])
            if not chunks:
                raise ValueError(f"no leaf chunks found for RAPTOR document {document_id!r}")
            tree = tree_builder.build(chunks)
            trees[document_id] = tree
            tree_manifest[document_id] = {
                "fingerprint": tree.fingerprint,
                "leaf_fingerprint": tree.leaf_fingerprint,
                "cache_path": str(tree.cache_path),
                "cache_hit": tree.cache_hit,
                "summary_node_count": len(tree.nodes),
                "summary_calls": tree.summary_calls if not tree.cache_hit else 0,
                "root_node_ids": list(tree.root_node_ids),
            }
        suite_manifest.update(
            {
                "status": "running",
                "index": {
                    "fingerprint": index.result.fingerprint,
                    "fingerprint_inputs": index.result.fingerprint_inputs,
                    "cache_hit": index.result.cache_hit,
                    "chunk_count": index.result.chunk_count,
                },
                "trees": tree_manifest,
                "tree_count": len(trees),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        index.close()
        index = None

        comparison_rows: list[dict[str, Any]] = []
        for variant in selected_variants:
            run_id = f"{selected_suite_id}-{variant.lower()}"
            result = run_qasper_benchmark(
                dataset,
                root=benchmark_directory,
                mode=normalized_mode,
                limit=selected_limit,
                seed=seed,
                config=source_config,
                embedding_provider=shared_embedding,
                reranker=shared_reranker,
                answerer=answerer,
                variant=None,
                raptor_variant=variant,
                raptor_trees=trees,
                run_id=run_id,
                rebuild_index=False,
            )
            from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run

            metrics = evaluate_qasper_run(result.run_directory, root=benchmark_directory)
            run_manifest = read_json(result.manifest_path) or {}
            row = {
                "variant_id": variant,
                "run_id": result.run_id,
                "run_directory": str(result.run_directory),
                "run_status": result.run_status,
                "error_count": result.error_count,
                "index_cache_hit": bool(run_manifest.get("index", {}).get("cache_hit")),
                "raptor_category_metrics": metrics.get("raptor_category_metrics", {}),
                "ai_trans_retrieval": metrics["ai_trans_retrieval"],
                "paragraph_evidence": metrics["paragraph_evidence"],
                "official_qasper": metrics["official_qasper"],
                "performance_ms": metrics["performance_ms"],
                "context_metrics": metrics.get("context_metrics", {}),
            }
            comparison_rows.append(row)
            suite_manifest["completed_runs"].append(
                {
                    "variant_id": variant,
                    "run_id": result.run_id,
                    "run_status": result.run_status,
                    "index_cache_hit": row["index_cache_hit"],
                }
            )
            atomic_write_json(manifest_path, suite_manifest)

        comparison = {
            "metric_version": 1,
            "suite_id": selected_suite_id,
            "variant_count": len(comparison_rows),
            "definition": {
                "index_rebuild": False,
                "summary_cache_excludes_query_time_parameters": True,
                "R0": "current dense + BM25 + structural retrieval + reranker",
                "R1": "dense leaf retrieval mixed with ranked RAPTOR summaries, expanded to leaves",
                "R2": "ranked summary nodes only, collapsed to descendant leaf evidence",
                "R3": "current dense + BM25 + RRF joined with RAPTOR summary candidates before reranking",
                "category_definition": {
                    "Local": "gold evidence paragraphs all belong to one QASPER section",
                    "Cross-section": "a complete annotator gold set spans two sections",
                    "Global": "a complete annotator gold set spans at least three sections",
                    "Overall": "all questions, including questions without mapped evidence",
                },
            },
            "variants": comparison_rows,
        }
        atomic_write_json(comparison_path, comparison)
        suite_manifest.update(
            {
                "status": "complete",
                "completed_at": datetime.now(UTC).isoformat(),
                "comparison_path": str(comparison_path),
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
    except BaseException as exc:
        suite_manifest.update(
            {
                "status": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        atomic_write_json(manifest_path, suite_manifest)
        raise
    finally:
        if index is not None:
            index.close()

    return QasperRaptorAblationSuiteResult(
        suite_id=selected_suite_id,
        suite_directory=suite_directory,
        manifest_path=manifest_path,
        comparison_path=comparison_path,
        variant_count=len(selected_variants),
        tree_count=len(trees),
        status="complete",
    )


__all__ = [
    "RUN_LIMITS",
    "GroundedQasperAnswerer",
    "QasperAblationSuiteResult",
    "QasperAdaptiveRetrievalSuiteResult",
    "QasperAnswerer",
    "QasperBenchmarkRunResult",
    "QasperEvidenceSelectionSuiteResult",
    "QasperGeneratedAnswer",
    "QasperRaptorAblationSuiteResult",
    "run_qasper_ablation",
    "run_qasper_adaptive_retrieval_ablation",
    "run_qasper_benchmark",
    "run_qasper_evidence_selection_ablation",
    "run_qasper_raptor_ablation",
]
