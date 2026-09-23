from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.rag.benchmarks.cache import (
    QASPER_ADAPTER_VERSION,
    IndexCacheFingerprint,
    build_index_cache_fingerprint,
)
from backend.rag.benchmarks.common import atomic_write_json, benchmark_root, read_json
from backend.rag.benchmarks.qasper.adapter import QasperAdaptedPaper, adapt_qasper_paper
from backend.rag.benchmarks.qasper.schema import QasperDataset, QasperPaper
from backend.rag.benchmarks.runtime import (
    BenchmarkRagRuntime,
    build_benchmark_rag_runtime,
)
from backend.rag.config import RagConfig
from backend.rag.embeddings.base import EmbeddingProvider
from backend.rag.index_manifest import IndexStatus, ready_manifest_record
from backend.rag.models import DocumentChunk
from backend.rag.rerankers.base import RerankerProvider


@dataclass(frozen=True, slots=True)
class QasperIndexBuildResult:
    fingerprint: str
    fingerprint_inputs: dict[str, object]
    index_root: Path
    index_manifest_path: Path
    cache_manifest_path: Path
    paper_count: int
    paragraph_count: int
    chunk_count: int
    cache_hit: bool
    reused_paper_count: int
    indexed_paper_count: int


@dataclass(slots=True)
class QasperBenchmarkIndex:
    runtime: BenchmarkRagRuntime
    result: QasperIndexBuildResult

    def close(self) -> None:
        self.runtime.close()


def _chunks_for_paper(
    paper: QasperPaper,
    *,
    split: str,
    adapted: QasperAdaptedPaper,
    runtime: BenchmarkRagRuntime,
) -> list[DocumentChunk]:
    chunks = runtime.chunker.chunk(adapted.document)
    if not chunks:
        raise ValueError(f"QASPER paper {paper.paper_id!r} produced no chunks")
    paragraph_spans = adapted.paragraphs
    enriched: list[DocumentChunk] = []
    for chunk in chunks:
        source_paragraph_ids = [
            paragraph.paragraph_id
            for paragraph in paragraph_spans
            if chunk.start_char < paragraph.end_char
            and chunk.end_char > paragraph.start_char
        ]
        if not source_paragraph_ids:
            raise ValueError(
                f"chunk {chunk.chunk_id!r} does not overlap a QASPER paragraph"
            )
        metadata = dict(chunk.metadata)
        metadata["benchmark"] = {
            "dataset": "qasper",
            "split": split,
            "paper_id": paper.paper_id,
            "source_paragraph_ids": source_paragraph_ids,
        }
        enriched.append(
            chunk.model_copy(
                update={
                    "embedding_version": runtime.embedding_provider.model_name,
                    "metadata": metadata,
                }
            )
        )
    return enriched


def _valid_existing_document(
    *,
    document_id: str,
    chunks: list[DocumentChunk],
    runtime: BenchmarkRagRuntime,
    sparse_chunk_ids: dict[str, set[str]],
) -> bool:
    record = runtime.manifest.get(document_id)
    if record is None or record.status is not IndexStatus.READY:
        return False
    expected_chunk_ids = {chunk.chunk_id for chunk in chunks}
    return (
        set(record.chunk_ids) == expected_chunk_ids
        and record.chunker_version == runtime.index_service.chunker_version
        and record.embedding_model == runtime.embedding_provider.model_name
        and record.embedding_dimension == runtime.embedding_provider.dimension
        and sparse_chunk_ids.get(document_id, set()) == expected_chunk_ids
        and runtime.vector_store.count_chunks([document_id]) == len(expected_chunk_ids)
    )


def _cache_is_valid(
    *,
    cache: dict[str, Any] | None,
    index_manifest: dict[str, Any] | None,
    fingerprint: IndexCacheFingerprint,
    dataset: QasperDataset,
    runtime: BenchmarkRagRuntime,
) -> bool:
    if cache is None or index_manifest is None:
        return False
    if cache.get("fingerprint") != fingerprint.as_dict():
        return False
    if cache.get("fingerprint_id") != fingerprint.digest:
        return False
    if index_manifest.get("fingerprint") != fingerprint.as_dict():
        return False
    if (
        index_manifest.get("fingerprint_id") != fingerprint.digest
        or index_manifest.get("sample_hash") != fingerprint.sample_hash
        or index_manifest.get("dataset") != "qasper"
        or index_manifest.get("dataset_version") != dataset.dataset_version
        or index_manifest.get("split") != dataset.split
        or index_manifest.get("paper_count") != len(dataset.papers)
    ):
        return False
    expected_document_ids = {
        f"qasper:{dataset.split}:{paper_id}" for paper_id in dataset.papers
    }
    document_chunk_ids = cache.get("document_chunk_ids")
    if not isinstance(document_chunk_ids, dict) or set(document_chunk_ids) != expected_document_ids:
        return False
    expected_chunk_ids: set[str] = set()
    for values in document_chunk_ids.values():
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            return False
        expected_chunk_ids.update(values)
    if len(expected_chunk_ids) != sum(len(values) for values in document_chunk_ids.values()):
        return False
    manifest_chunk_ids = index_manifest.get("document_chunk_ids")
    if manifest_chunk_ids != document_chunk_ids:
        return False
    if index_manifest.get("chunk_count") != len(expected_chunk_ids):
        return False

    records = {record.document_id: record for record in runtime.manifest.list_records()}
    if set(records) != expected_document_ids:
        return False
    for document_id, chunk_ids in document_chunk_ids.items():
        record = records.get(document_id)
        if (
            record is None
            or record.status is not IndexStatus.READY
            or set(record.chunk_ids) != set(chunk_ids)
            or record.chunker_version != runtime.index_service.chunker_version
            or record.embedding_model != runtime.embedding_provider.model_name
            or record.embedding_dimension != runtime.embedding_provider.dimension
            or runtime.vector_store.count_chunks([document_id]) != len(chunk_ids)
        ):
            return False
    sparse_chunk_ids = {
        chunk.chunk_id
        for chunk in runtime.sparse_retriever.list_chunks()
        if chunk.document_id in expected_document_ids
    }
    if sparse_chunk_ids != expected_chunk_ids:
        return False
    return (
        runtime.vector_store.count_chunks(sorted(expected_document_ids))
        == len(expected_chunk_ids)
    )


def _index_one_paper(
    paper: QasperPaper,
    *,
    adapted: QasperAdaptedPaper,
    chunks: list[DocumentChunk],
    runtime: BenchmarkRagRuntime,
) -> None:
    document = adapted.document.document
    document_id = document.document_id
    existing = runtime.manifest.get(document_id)
    runtime.manifest.mark_status(
        document_id,
        IndexStatus.CHUNKING,
        source_uri=document.source_uri,
    )
    try:
        runtime.manifest.mark_status(document_id, IndexStatus.EMBEDDING)
        vectors = runtime.embedding_provider.embed_documents([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("embedding provider returned a vector count mismatch")

        # Remove any partial/stale copy only after new vectors have been created.
        runtime.vector_store.delete_document(document_id)
        runtime.sparse_retriever.delete_document(document_id)
        if existing is not None:
            runtime.manifest.delete(document_id)
        runtime.manifest.mark_status(document_id, IndexStatus.INDEXING)
        runtime.vector_store.upsert_chunks(chunks, vectors)
        runtime.sparse_retriever.index_chunks(chunks)
        runtime.manifest.upsert(
            ready_manifest_record(
                document_id=document_id,
                content_hash=document.content_hash,
                source_uri=document.source_uri,
                title=document.title,
                parser_version=QASPER_ADAPTER_VERSION,
                chunker_version=runtime.index_service.chunker_version,
                embedding_model=runtime.embedding_provider.model_name,
                embedding_dimension=runtime.embedding_provider.dimension,
                chunk_ids=[chunk.chunk_id for chunk in chunks],
                structure_quality="structured",
                section_count=len(adapted.document.sections),
            )
        )
    except Exception as exc:
        runtime.manifest.mark_status(
            document_id,
            IndexStatus.FAILED,
            source_uri=document.source_uri,
            error=str(exc) or exc.__class__.__name__,
        )
        raise


def build_qasper_index(
    dataset: QasperDataset,
    *,
    storage_root: str | Path | None = None,
    config: RagConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: RerankerProvider | None = None,
    rebuild: bool = False,
) -> QasperBenchmarkIndex:
    """Build or reuse the isolated QASPER index for one fingerprint."""

    source_config = (config or RagConfig()).model_copy(deep=True)
    if embedding_provider is not None:
        if embedding_provider.dimension != source_config.embedding.dimension:
            raise ValueError(
                "embedding provider dimension does not match benchmark RAG config"
            )
        provider_model = embedding_provider.model_name.strip()
        if provider_model:
            source_config.embedding = source_config.embedding.model_copy(
                update={"model": provider_model}
            )
    fingerprint = build_index_cache_fingerprint(dataset, source_config)
    root = benchmark_root(storage_root)
    index_root = root / "indexes" / fingerprint.digest
    cache_manifest_path = root / "cache" / f"{fingerprint.digest}.json"
    index_manifest_path = root / "manifests" / f"index-{fingerprint.digest}.json"
    runtime = build_benchmark_rag_runtime(
        index_root,
        config=source_config,
        embedding_provider=embedding_provider,
        reranker=reranker,
    )
    cached = read_json(cache_manifest_path)
    index_manifest = read_json(index_manifest_path)
    if not rebuild and _cache_is_valid(
        cache=cached,
        index_manifest=index_manifest,
        fingerprint=fingerprint,
        dataset=dataset,
        runtime=runtime,
    ):
        document_chunk_ids = cached["document_chunk_ids"]
        return QasperBenchmarkIndex(
            runtime=runtime,
            result=QasperIndexBuildResult(
                fingerprint=fingerprint.digest,
                fingerprint_inputs=fingerprint.as_dict(),
                index_root=index_root,
                index_manifest_path=index_manifest_path,
                cache_manifest_path=cache_manifest_path,
                paper_count=len(dataset.papers),
                paragraph_count=sum(len(paper.paragraphs) for paper in dataset.papers.values()),
                chunk_count=sum(len(ids) for ids in document_chunk_ids.values()),
                cache_hit=True,
                reused_paper_count=len(dataset.papers),
                indexed_paper_count=0,
            ),
        )

    sparse_chunk_ids: dict[str, set[str]] = {}
    for chunk in runtime.sparse_retriever.list_chunks():
        sparse_chunk_ids.setdefault(chunk.document_id, set()).add(chunk.chunk_id)

    document_chunk_ids: dict[str, list[str]] = {}
    indexed_papers = 0
    reused_papers = 0
    paragraph_count = 0
    chunk_count = 0
    try:
        for paper in sorted(dataset.papers.values(), key=lambda item: item.paper_id):
            adapted = adapt_qasper_paper(paper, split=dataset.split)
            chunks = _chunks_for_paper(
                paper,
                split=dataset.split,
                adapted=adapted,
                runtime=runtime,
            )
            document_id = adapted.document.document.document_id
            paragraph_count += len(adapted.paragraphs)
            if not rebuild and _valid_existing_document(
                document_id=document_id,
                chunks=chunks,
                runtime=runtime,
                sparse_chunk_ids=sparse_chunk_ids,
            ):
                reused_papers += 1
            else:
                _index_one_paper(
                    paper,
                    adapted=adapted,
                    chunks=chunks,
                    runtime=runtime,
                )
                sparse_chunk_ids[document_id] = {chunk.chunk_id for chunk in chunks}
                indexed_papers += 1
            chunk_ids = [chunk.chunk_id for chunk in chunks]
            document_chunk_ids[document_id] = chunk_ids
            chunk_count += len(chunk_ids)

        completed_at = datetime.now(UTC).isoformat()
        manifest_payload: dict[str, Any] = {
            "manifest_version": 1,
            "dataset": "qasper",
            "dataset_version": dataset.dataset_version,
            "split": dataset.split,
            "source_sha256": dataset.source_sha256,
            "sample_hash": fingerprint.sample_hash,
            "fingerprint": fingerprint.as_dict(),
            "fingerprint_id": fingerprint.digest,
            "index_root": str(index_root),
            "paper_count": len(dataset.papers),
            "question_count": len(dataset.questions),
            "paragraph_count": paragraph_count,
            "chunk_count": chunk_count,
            "document_chunk_ids": document_chunk_ids,
            "embedding_model": runtime.embedding_provider.model_name,
            "embedding_dimension": runtime.embedding_provider.dimension,
            "chunker_version": runtime.index_service.chunker_version,
            "created_at": completed_at,
        }
        atomic_write_json(index_manifest_path, manifest_payload)
        cache_payload = {
            "cache_version": 1,
            "fingerprint": fingerprint.as_dict(),
            "fingerprint_id": fingerprint.digest,
            "index_manifest": str(index_manifest_path),
            "document_chunk_ids": document_chunk_ids,
            "chunk_count": chunk_count,
            "completed_at": completed_at,
        }
        atomic_write_json(cache_manifest_path, cache_payload)
    except Exception:
        runtime.close()
        raise

    return QasperBenchmarkIndex(
        runtime=runtime,
        result=QasperIndexBuildResult(
            fingerprint=fingerprint.digest,
            fingerprint_inputs=fingerprint.as_dict(),
            index_root=index_root,
            index_manifest_path=index_manifest_path,
            cache_manifest_path=cache_manifest_path,
            paper_count=len(dataset.papers),
            paragraph_count=paragraph_count,
            chunk_count=chunk_count,
            cache_hit=False,
            reused_paper_count=reused_papers,
            indexed_paper_count=indexed_papers,
        ),
    )


__all__ = [
    "QasperBenchmarkIndex",
    "QasperIndexBuildResult",
    "build_qasper_index",
]
