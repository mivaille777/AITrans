from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.rag.chunking import CHUNKER_VERSION, StructureAwareChunker
from backend.rag.config import RagVisualUnderstandingConfig
from backend.rag.embeddings.base import EmbeddingProvider, embedding_fingerprint
from backend.rag.exceptions import RagInvariantError
from backend.rag.index_manifest import (
    IndexGenerationStatus,
    IndexManifest,
    IndexManifestRecord,
    IndexStatus,
    ready_manifest_record,
)
from backend.rag.models import DocumentChunk, NormalizedDocument
from backend.rag.multimodal import (
    MULTIMODAL_INDEX_VERSION,
    build_multimodal_chunks,
    delete_document_assets,
)
from backend.rag.parsers import parse_document
from backend.rag.source_span import SourceSpan, SourceSpanError, resolve_source_span
from backend.rag.sparse.store import SparseRetriever
from backend.rag.stores.base import VectorStore
from backend.rag.vision import (
    VisualDescriptionProvider,
    enrich_document_with_visual_descriptions,
    visual_description_index_version,
)

if TYPE_CHECKING:
    from backend.rag.graph.indexer import GraphIndexer

ParseDocument = Callable[[str | Path], NormalizedDocument]


class IndexDocumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    status: IndexStatus
    chunk_count: int = Field(default=0, ge=0)
    content_hash: str = ""
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    reused_existing: bool = False
    error: str = ""


class IndexService:
    """Coordinate parse, visual enrichment, chunking, embedding, and indexing."""

    def __init__(
        self,
        *,
        chunker: StructureAwareChunker,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        manifest: IndexManifest,
        parser: ParseDocument = parse_document,
        sparse_retriever: SparseRetriever | None = None,
        visual_description_provider: VisualDescriptionProvider | None = None,
        visual_understanding_config: RagVisualUnderstandingConfig | None = None,
        graph_indexer: GraphIndexer | None = None,
        graph_document_deleter: Callable[[str], None] | None = None,
    ) -> None:
        self._chunker = chunker
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._manifest = manifest
        self._parser = parser
        self._sparse_retriever = sparse_retriever
        self._graph_indexer = graph_indexer
        self._graph_document_deleter = graph_document_deleter
        if graph_indexer is not None:
            graph_indexer.recover(manifest)
        self._visual_description_provider = visual_description_provider
        self._visual_understanding_config = (
            visual_understanding_config.model_copy(deep=True)
            if visual_understanding_config is not None
            else RagVisualUnderstandingConfig()
        )

    @property
    def chunker_version(self) -> str:
        configured = str(getattr(self._chunker, "version", "") or "").strip()
        base_version = configured or CHUNKER_VERSION
        visual_version = visual_description_index_version(
            self._visual_understanding_config
        )
        return f"{base_version}+{MULTIMODAL_INDEX_VERSION}+{visual_version}"

    def index_document(self, path: str | Path) -> IndexDocumentResult:
        return self._index_document(path, force=False)

    def reindex_document(self, path_or_document_id: str | Path) -> IndexDocumentResult:
        candidate = Path(path_or_document_id)
        if candidate.exists():
            return self._index_document(candidate, force=True)
        record = self._manifest.get(str(path_or_document_id))
        if record is None or not record.source_uri:
            document_id = str(path_or_document_id)
            return IndexDocumentResult(
                document_id=document_id or "unknown",
                status=IndexStatus.FAILED,
                error=f"indexed document not found: {document_id}",
            )
        return self._index_document(
            self._path_from_file_uri(record.source_uri), force=True
        )

    def delete_document(self, document_id: str) -> bool:
        record = self._manifest.get(document_id)
        if record is None:
            return False
        if self._graph_indexer is not None:
            self._graph_indexer.delete_document(document_id)
        elif self._graph_document_deleter is not None:
            self._graph_document_deleter(document_id)
        self._vector_store.delete_document(document_id)
        if self._sparse_retriever is not None:
            self._sparse_retriever.delete_document(document_id)
        if record.source_uri:
            delete_document_assets(record.source_uri)
        self._manifest.delete(document_id)
        return True

    def get_index_status(self, document_id: str) -> IndexManifestRecord | None:
        return self._manifest.get(document_id)

    def _index_document(
        self,
        path: str | Path,
        *,
        force: bool,
    ) -> IndexDocumentResult:
        started = perf_counter()
        source_path = Path(path).expanduser().resolve()
        source_uri = source_path.as_uri()
        existing = self._manifest.find_by_source_uri(source_uri)
        document_id = (
            existing.document_id if existing else self._stable_document_id(source_uri)
        )
        content_hash = existing.content_hash if existing else ""
        keep_existing_ready = bool(
            existing is not None and existing.status is IndexStatus.READY
        )
        generation_id = ""
        generation_started = False

        self._mark_progress(
            document_id,
            IndexStatus.PARSING,
            source_uri=source_uri,
            preserve_ready=keep_existing_ready,
        )
        try:
            normalized = self._parser(source_path)
            normalized = normalized.model_copy(
                update={
                    "document": normalized.document.model_copy(
                        update={
                            "document_id": document_id,
                            "source_uri": source_uri,
                        }
                    ),
                    "elements": [
                        element.model_copy(update={"document_id": document_id})
                        for element in normalized.elements
                    ],
                }
            )
            content_hash = normalized.document.content_hash
            parser_version = str(normalized.metadata.get("parser_version", ""))
            structure_quality, reindex_recommended = self._structure_quality(normalized)

            if (
                not force
                and existing is not None
                and self._can_reuse(existing, content_hash, parser_version)
            ):
                self._manifest.upsert(existing)
                return self._result(
                    started,
                    document_id=document_id,
                    status=IndexStatus.READY,
                    chunk_count=len(existing.chunk_ids),
                    content_hash=content_hash,
                    reused_existing=True,
                )

            # VLM work is deliberately after the reuse check: unchanged documents
            # must not pay for repeated image descriptions. Each image degrades
            # independently to its caption-based surrogate on provider failure.
            normalized = enrich_document_with_visual_descriptions(
                normalized,
                config=self._visual_understanding_config,
                provider=self._visual_description_provider,
            )

            self._mark_progress(
                document_id,
                IndexStatus.CHUNKING,
                source_uri=source_uri,
                preserve_ready=keep_existing_ready,
            )
            text_chunks = self._chunker.chunk(normalized)
            text_chunks = self._ensure_text_chunk_source_spans(
                normalized,
                text_chunks,
            )
            multimodal_chunks = build_multimodal_chunks(
                normalized,
                start_index=len(text_chunks),
                chunker_version=self.chunker_version,
            )
            chunks = [*text_chunks, *multimodal_chunks]
            if not chunks:
                raise ValueError("document produced no indexable chunks")

            embedding_version = self._embedding_provider.model_name
            chunks = [
                chunk.model_copy(update={"embedding_version": embedding_version})
                for chunk in chunks
            ]
            self._mark_progress(
                document_id,
                IndexStatus.EMBEDDING,
                source_uri=source_uri,
                preserve_ready=keep_existing_ready,
            )
            vectors = self._embedding_provider.embed_documents(
                [chunk.text for chunk in chunks]
            )

            self._mark_progress(
                document_id,
                IndexStatus.INDEXING,
                source_uri=source_uri,
                preserve_ready=keep_existing_ready,
            )
            new_chunk_ids = [chunk.chunk_id for chunk in chunks]
            generation_id = uuid4().hex
            self._manifest.begin_generation(document_id, generation_id, new_chunk_ids)
            generation_started = True
            self._vector_store.upsert_chunks(
                chunks,
                vectors,
                generation_id=generation_id,
            )
            if self._sparse_retriever is not None:
                self._sparse_retriever.index_chunks(
                    chunks,
                    generation_id=generation_id,
                )

            vector_chunk_ids = [
                chunk.chunk_id
                for chunk in self._vector_store.list_chunks(generation_id=generation_id)
                if chunk.document_id == document_id
            ]
            self._require_exact_chunk_ids(
                "vector store",
                expected=new_chunk_ids,
                observed=vector_chunk_ids,
            )
            if self._sparse_retriever is not None:
                sparse_chunk_ids = [
                    chunk.chunk_id
                    for chunk in self._sparse_retriever.list_chunks(
                        generation_id=generation_id
                    )
                    if chunk.document_id == document_id
                ]
                self._require_exact_chunk_ids(
                    "BM25 store",
                    expected=new_chunk_ids,
                    observed=sparse_chunk_ids,
                )
                if Counter(sparse_chunk_ids) != Counter(vector_chunk_ids):
                    raise ValueError(
                        "vector/BM25 generation chunk IDs differ: "
                        f"vector={sorted(vector_chunk_ids)}, "
                        f"BM25={sorted(sparse_chunk_ids)}"
                    )
            graph_validation = {}
            if self._graph_indexer is not None:
                graph = self._graph_indexer.build_generation(
                    normalized, chunks, generation_id
                )
                graph_validation = {
                    "graph_chunk_ids": graph.generation.chunk_ids,
                    "graph_scope_id": graph.generation.scope_id,
                    "graph_index_version": graph.generation.index_version,
                }
            self._manifest.validate_generation(
                document_id,
                generation_id,
                vector_chunk_ids,
                **graph_validation,
            )

            record = ready_manifest_record(
                document_id=document_id,
                content_hash=content_hash,
                source_uri=source_uri,
                title=normalized.document.title,
                parser_version=parser_version,
                chunker_version=self.chunker_version,
                embedding_model=self._embedding_provider.model_name,
                embedding_dimension=self._embedding_provider.dimension,
                embedding_fingerprint=embedding_fingerprint(self._embedding_provider),
                chunk_ids=new_chunk_ids,
                structure_quality=structure_quality,
                section_count=len(normalized.sections),
                reindex_recommended=reindex_recommended,
            ).model_copy(
                update={
                    "generation_id": generation_id,
                    "graph_scope_id": graph_validation.get("graph_scope_id", ""),
                    "graph_index_version": graph_validation.get("graph_index_version", ""),
                }
            )
            self._manifest.publish_generation(
                document_id,
                generation_id,
                manifest_record=record,
            )
            return self._result(
                started,
                document_id=document_id,
                status=IndexStatus.READY,
                chunk_count=len(chunks),
                content_hash=content_hash,
            )
        except Exception as exc:  # noqa: BLE001 - service boundary returns typed failures
            error = str(exc) or exc.__class__.__name__
            if generation_started:
                cleanup_errors: list[str] = []
                if self._graph_indexer is not None:
                    try:
                        self._graph_indexer.delete_generation(
                            document_id, generation_id
                        )
                    except Exception as cleanup_exc:  # noqa: BLE001 - preserve root cause
                        cleanup_errors.append(
                            "Graph cleanup: "
                            + (str(cleanup_exc) or cleanup_exc.__class__.__name__)
                        )
                try:
                    self._vector_store.delete_document(
                        document_id,
                        generation_id=generation_id,
                    )
                except Exception as cleanup_exc:  # noqa: BLE001 - preserve root cause
                    cleanup_errors.append(
                        "Qdrant cleanup: "
                        + (str(cleanup_exc) or cleanup_exc.__class__.__name__)
                    )
                if self._sparse_retriever is not None:
                    try:
                        self._sparse_retriever.delete_document(
                            document_id,
                            generation_id=generation_id,
                        )
                    except Exception as cleanup_exc:  # noqa: BLE001 - preserve root cause
                        cleanup_errors.append(
                            "BM25 cleanup: "
                            + (str(cleanup_exc) or cleanup_exc.__class__.__name__)
                        )
                if cleanup_errors:
                    error = f"{error}; generation cleanup failed: {'; '.join(cleanup_errors)}"
                generation = self._manifest.get_generation(document_id, generation_id)
                if generation and generation.status in {
                    IndexGenerationStatus.BUILDING,
                    IndexGenerationStatus.VALIDATING,
                }:
                    self._manifest.fail_generation(
                        document_id,
                        generation_id,
                        error=error,
                    )
            if not keep_existing_ready:
                self._manifest.mark_status(
                    document_id,
                    IndexStatus.FAILED,
                    source_uri=source_uri,
                    error=error,
                )
            return self._result(
                started,
                document_id=document_id,
                status=IndexStatus.FAILED,
                content_hash=content_hash,
                error=error,
            )

    def _mark_progress(
        self,
        document_id: str,
        status: IndexStatus,
        *,
        source_uri: str,
        preserve_ready: bool,
    ) -> None:
        if preserve_ready:
            return
        self._manifest.mark_status(
            document_id,
            status,
            source_uri=source_uri,
        )

    @staticmethod
    def _require_exact_chunk_ids(
        store_name: str,
        *,
        expected: list[str],
        observed: list[str],
    ) -> None:
        expected_counts = Counter(expected)
        observed_counts = Counter(observed)
        if expected_counts == observed_counts:
            return
        missing = sorted((expected_counts - observed_counts).elements())
        unexpected = sorted((observed_counts - expected_counts).elements())
        raise ValueError(
            f"{store_name} generation chunk IDs failed validation: "
            f"missing={missing}, unexpected={unexpected}"
        )

    def _can_reuse(
        self,
        record: IndexManifestRecord,
        content_hash: str,
        parser_version: str,
    ) -> bool:
        return (
            record.status is IndexStatus.READY
            and record.content_hash == content_hash
            and record.parser_version == parser_version
            and record.chunker_version == self.chunker_version
            and record.embedding_model == self._embedding_provider.model_name
            and record.embedding_dimension == self._embedding_provider.dimension
            and record.embedding_fingerprint
            == embedding_fingerprint(self._embedding_provider).as_dict()
            and (
                self._graph_indexer is None or self._graph_indexer.can_reuse(record)
            )
        )

    @staticmethod
    def _ensure_text_chunk_source_spans(
        document: NormalizedDocument,
        chunks: list[DocumentChunk],
    ) -> list[DocumentChunk]:
        """Verify every text evidence chunk and attach a span for compatible chunkers."""

        source = document.document
        normalized_text = document.text
        if not source.content_hash:
            raise RagInvariantError(
                "normalized document content_hash must not be empty"
            )

        verified: list[DocumentChunk] = []
        for chunk in chunks:
            if not chunk.text.strip():
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} contains empty evidence text"
                )
            if chunk.document_id != source.document_id:
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} points to a different document"
                )
            if chunk.document_hash and chunk.document_hash != source.content_hash:
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} points to a different document version"
                )
            if chunk.source_uri and chunk.source_uri != source.source_uri:
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} points to a different source URI"
                )
            if (
                chunk.start_char < 0
                or chunk.end_char <= chunk.start_char
                or chunk.end_char > len(normalized_text)
            ):
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} has an invalid source character range"
                )
            selected_text = normalized_text[chunk.start_char : chunk.end_char]
            if selected_text != chunk.text:
                raise RagInvariantError(
                    f"source span does not match chunk evidence for {chunk.chunk_id!r}"
                )

            page_start = chunk.metadata.get("page_start", chunk.page_number)
            page_end = chunk.metadata.get("page_end", chunk.page_number)
            if (page_start is None) != (page_end is None):
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} has an incomplete source page range"
                )
            if page_start is not None:
                try:
                    page_start = int(page_start)
                    page_end = int(page_end)
                except (TypeError, ValueError) as exc:
                    raise RagInvariantError(
                        f"chunk {chunk.chunk_id!r} has an invalid source page range"
                    ) from exc
                if page_start < 1 or page_end < page_start:
                    raise RagInvariantError(
                        f"chunk {chunk.chunk_id!r} has an invalid source page range"
                    )

            intersecting_pages = sorted(
                (
                    page
                    for page in document.pages
                    if chunk.start_char < page.end_char
                    and chunk.end_char > page.start_char
                ),
                key=lambda page: page.page_number,
            )
            expected_page_range = (
                (intersecting_pages[0].page_number, intersecting_pages[-1].page_number)
                if intersecting_pages
                else (None, None)
            )
            if (page_start, page_end) != expected_page_range:
                raise RagInvariantError(
                    f"source page range does not match normalized document pages "
                    f"for chunk {chunk.chunk_id!r}"
                )
            expected_page_number = expected_page_range[0]
            if chunk.page_number != expected_page_number:
                raise RagInvariantError(
                    f"chunk {chunk.chunk_id!r} page_number does not match its source span"
                )

            span = chunk.source_span
            if span is None:
                span = SourceSpan.from_text(
                    normalized_text,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    document_hash=source.content_hash,
                    source_uri=source.source_uri,
                    page_start=page_start,
                    page_end=page_end,
                )
                chunk = chunk.model_copy(
                    update={
                        "document_hash": source.content_hash,
                        "source_uri": source.source_uri,
                        "source_span": span,
                    }
                )
            else:
                if span.source_uri and span.source_uri != source.source_uri:
                    raise RagInvariantError(
                        f"source span for {chunk.chunk_id!r} points to a different source URI"
                    )
                if (span.page_start, span.page_end) != (page_start, page_end):
                    raise RagInvariantError(
                        f"source span for {chunk.chunk_id!r} has a different source page range"
                    )
                try:
                    resolved = resolve_source_span(
                        span,
                        normalized_text,
                        expected_document_hash=source.content_hash,
                    )
                except SourceSpanError as exc:
                    raise RagInvariantError(
                        f"source span for {chunk.chunk_id!r} is invalid: {exc}"
                    ) from exc
                if resolved != chunk.text:
                    raise RagInvariantError(
                        f"source span does not match chunk evidence for {chunk.chunk_id!r}"
                    )
            verified.append(chunk)
        return verified

    @staticmethod
    def _structure_quality(document: NormalizedDocument) -> tuple[str, bool]:
        """Expose parsing quality instead of silently treating PDF fallback as equal."""

        parser_version = str(document.metadata.get("parser_version", "")).casefold()
        fallback = bool(document.metadata.get("advanced_parser_fallback"))
        is_pdf = document.document.source_kind.casefold() == "pdf"
        headings = sum(1 for section in document.sections if section.heading.strip())
        if is_pdf and (fallback or parser_version.startswith("pypdf")):
            return "basic", True
        if is_pdf and headings == 0:
            return "degraded", True
        return "structured", False

    @staticmethod
    def _result(
        started: float,
        *,
        document_id: str,
        status: IndexStatus,
        chunk_count: int = 0,
        content_hash: str = "",
        reused_existing: bool = False,
        error: str = "",
    ) -> IndexDocumentResult:
        return IndexDocumentResult(
            document_id=document_id,
            status=status,
            chunk_count=chunk_count,
            content_hash=content_hash,
            elapsed_ms=(perf_counter() - started) * 1000,
            reused_existing=reused_existing,
            error=error,
        )

    @staticmethod
    def _stable_document_id(source_uri: str) -> str:
        digest = sha256(source_uri.casefold().encode("utf-8")).hexdigest()
        return f"doc_{digest[:24]}"

    @staticmethod
    def _path_from_file_uri(source_uri: str) -> Path:
        parsed = urlparse(source_uri)
        if parsed.scheme != "file":
            raise ValueError(f"document source is not a file URI: {source_uri}")
        raw_path = url2pathname(unquote(parsed.path))
        if os.name == "nt" and re.match(r"^[/\\][A-Za-z]:", raw_path):
            raw_path = raw_path[1:]
        if parsed.netloc:
            raw_path = f"//{parsed.netloc}{raw_path}"
        return Path(raw_path)


__all__ = ["IndexDocumentResult", "IndexService"]
