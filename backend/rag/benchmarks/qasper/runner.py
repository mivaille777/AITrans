from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
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
from backend.rag.model_manager import ModelManager
from backend.rag.models import RetrievalResult
from backend.rag.query_planner import RagQueryPlan, merge_query_results
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
    selected_variant = get_qasper_ablation_variant(variant)
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
    try:
        index = build_qasper_index(
            selected,
            storage_root=benchmark_directory,
            config=source_config,
            embedding_provider=embedding_provider,
            reranker=reranker,
            rebuild=rebuild_index,
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
                retrieval_started = perf_counter()
                try:
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
                    "sufficiency": sufficiency if retrieval_result is not None else None,
                    **(
                        {"second_round": len(retrieval_rounds) > 1}
                        if selected_variant.evidence_gate and retrieval_result is not None
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


__all__ = [
    "RUN_LIMITS",
    "GroundedQasperAnswerer",
    "QasperAblationSuiteResult",
    "QasperAnswerer",
    "QasperBenchmarkRunResult",
    "QasperGeneratedAnswer",
    "run_qasper_ablation",
    "run_qasper_benchmark",
]
