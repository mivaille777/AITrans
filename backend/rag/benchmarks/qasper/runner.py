from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from app.ai.chat.models import ChatContext, ChatRequest
from app.ai.chat.service import AIChatService
from app.ai.gateway import LLMGateway
from backend.rag.benchmarks.cache import qasper_sample_hash
from backend.rag.benchmarks.common import (
    atomic_write_json,
    atomic_write_jsonl,
    benchmark_root,
)
from backend.rag.benchmarks.qasper.alignment import align_qasper_evidence
from backend.rag.benchmarks.qasper.index import build_qasper_index
from backend.rag.benchmarks.qasper.sampling import sample_qasper_dataset
from backend.rag.benchmarks.qasper.schema import QasperDataset, QasperQuestion
from backend.rag.citation_service import build_evidence_citations
from backend.rag.config import RagConfig
from backend.rag.evaluation import percentile
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.models import RetrievalResult
from backend.rag.stores.base import VectorSearchFilter
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
        started = perf_counter()
        result = self._grounded.send_verified(
            evidence=evidence,
            citations=citations,
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


def _candidate_trace(candidate: Any) -> dict[str, Any]:
    chunk = candidate.chunk
    context_window = candidate.context_window
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "rank": candidate.rank,
        "text": chunk.text,
        "title": chunk.title,
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
                    retrieval_result = index.runtime.retrieval_service.retrieve(
                        question.question,
                        filters=VectorSearchFilter(document_ids=[document_id]),
                        final_top_k=BENCHMARK_FINAL_TOP_K,
                    )
                    retrieval_ms = (perf_counter() - retrieval_started) * 1000
                    retrieval_latencies.append(retrieval_ms)
                    strategy_counts[retrieval_result.retrieval_strategy] = (
                        strategy_counts.get(retrieval_result.retrieval_strategy, 0) + 1
                    )
                    returned_document_ids = {
                        item.chunk.document_id for item in retrieval_result.candidates
                    }
                    if returned_document_ids.difference({document_id}):
                        retrieval_result = None
                        raise RuntimeError(
                            "known-paper retrieval returned a chunk from another paper"
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


__all__ = [
    "RUN_LIMITS",
    "GroundedQasperAnswerer",
    "QasperAnswerer",
    "QasperBenchmarkRunResult",
    "QasperGeneratedAnswer",
    "run_qasper_benchmark",
]
