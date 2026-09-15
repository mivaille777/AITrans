from __future__ import annotations

from pathlib import Path

from backend.evaluation.visual_retrieval_benchmark import (
    VisualRetrievalBenchmarkCase,
    load_visual_retrieval_benchmark_cases,
    recall_at_k,
    reciprocal_rank,
    run_visual_retrieval_benchmark,
)
from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.visual_adaptive import AdaptivePrefetchPolicy


def _candidate(chunk_id: str, rank: int, *, reduction: float) -> RetrievalCandidate:
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        text=chunk_id,
        title="Paper",
        page_number=rank,
        chunk_index=rank - 1,
        token_count=1,
        source_uri="file:///paper.pdf",
        document_hash="hash",
        parser_version="parser",
        chunker_version="chunker",
        embedding_version="visual",
        metadata={"source_kind": "pdf"},
    )
    return RetrievalCandidate(
        chunk=chunk,
        rank=rank,
        metadata={
            "retrieval_channel": "visual",
            "visual_prefetch_k": 24,
            "visual_candidate_count": 100,
            "visual_prefetch_adaptive": True,
            "visual_maxsim_candidate_reduction": reduction,
        },
    )


class _Provider:
    def embed_query(self, query: str):
        return [[1.0, 0.0]]


class _FixedStore:
    def __init__(self, ids):
        self.ids = ids

    def search(self, query, *, top_k, filters=None):
        return [
            _candidate(chunk_id, rank, reduction=0.76)
            for rank, chunk_id in enumerate(self.ids[:top_k], start=1)
        ]


class _Store:
    prefetch_policy = AdaptivePrefetchPolicy(enabled=True)

    def search_full_maxsim(self, query, *, top_k, filters=None):
        return [
            _candidate(chunk_id, rank, reduction=0.0)
            for rank, chunk_id in enumerate(("a", "b", "c")[:top_k], start=1)
        ]

    def search(self, query, *, top_k, filters=None):
        return [
            _candidate(chunk_id, rank, reduction=0.5)
            for rank, chunk_id in enumerate(("a", "b", "c")[:top_k], start=1)
        ]

    def fixed_prefetch_store(self, prefetch_k: int):
        return _FixedStore(("a", "x", "c"))


def test_retrieval_metrics_are_grounded_in_relevant_ids() -> None:
    assert recall_at_k(("a", "x"), ("a", "b"), 2) == 0.5
    assert reciprocal_rank(("x", "b", "a"), ("a", "b")) == 0.5


def test_benchmark_uses_full_maxsim_as_oracle_without_labels() -> None:
    report = run_visual_retrieval_benchmark(
        (
            VisualRetrievalBenchmarkCase(
                case_id="case-1",
                query="diagram",
            ),
        ),
        provider=_Provider(),  # type: ignore[arg-type]
        store=_Store(),  # type: ignore[arg-type]
        config=RagVisualRetrievalConfig(
            enabled=True,
            dimension=2,
            visual_top_k=2,
        ),
        fixed_prefetch_ks=(24,),
        top_k=2,
        repeats=1,
        warmup=0,
    )

    adaptive = next(item for item in report.cases if item.mode == "adaptive")
    fixed = next(item for item in report.cases if item.mode == "fixed_24")
    assert adaptive.relevance_source == "full_maxsim_oracle"
    assert adaptive.recall_at_k == 1.0
    assert fixed.recall_at_k == 0.5
    assert {summary.mode for summary in report.summaries} == {"adaptive", "fixed_24"}


def test_benchmark_loader_accepts_optional_case_id(tmp_path: Path) -> None:
    dataset = tmp_path / "queries.jsonl"
    dataset.write_text(
        '{"query":"first","relevant_chunk_ids":["a"]}\n'
        '{"case_id":"named","query":"second","document_ids":["doc-1"]}\n',
        encoding="utf-8",
    )

    cases = load_visual_retrieval_benchmark_cases(dataset)

    assert cases[0].case_id == "case-0001"
    assert cases[1].case_id == "named"
    assert cases[1].document_ids == ("doc-1",)
