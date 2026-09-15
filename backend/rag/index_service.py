from __future__ import annotations

import os
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from pydantic import BaseModel, ConfigDict, Field

from backend.rag.chunking import CHUNKER_VERSION, StructureAwareChunker
from backend.rag.config import RagVisualUnderstandingConfig
from backend.rag.embeddings.base import EmbeddingProvider
from backend.rag.index_manifest import (
    IndexManifest,
    IndexManifestRecord,
    IndexStatus,
    ready_manifest_record,
)
from backend.rag.models import NormalizedDocument
from backend.rag.multimodal import (
    MULTIMODAL_INDEX_VERSION,
    build_multimodal_chunks,
    delete_document_assets,
)
from backend.rag.parsers import parse_document
from backend.rag.sparse.store import SparseRetriever
from backend.rag.stores.base import VectorStore
from backend.rag.vision import (
    VisualDescriptionProvider,
    enrich_document_with_visual_descriptions,
    visual_description_index_version,
)

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
    ) -> None:
        self._chunker = chunker
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._manifest = manifest
        self._parser = parser
        self._sparse_retriever = sparse_retriever
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

        self._manifest.mark_status(
            document_id,
            IndexStatus.PARSING,
            source_uri=source_uri,
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

            self._manifest.mark_status(document_id, IndexStatus.CHUNKING)
            text_chunks = self._chunker.chunk(normalized)
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
            self._manifest.mark_status(document_id, IndexStatus.EMBEDDING)
            vectors = self._embedding_provider.embed_documents(
                [chunk.text for chunk in chunks]
            )

            self._manifest.mark_status(document_id, IndexStatus.INDEXING)
            self._vector_store.upsert_chunks(chunks, vectors)
            if self._sparse_retriever is not None:
                self._sparse_retriever.delete_document(document_id)
                self._sparse_retriever.index_chunks(chunks)
            new_chunk_ids = [chunk.chunk_id for chunk in chunks]
            stale_chunk_ids = (
                sorted(set(existing.chunk_ids) - set(new_chunk_ids)) if existing else []
            )
            if stale_chunk_ids:
                self._vector_store.delete_chunks(stale_chunk_ids)

            record = ready_manifest_record(
                document_id=document_id,
                content_hash=content_hash,
                source_uri=source_uri,
                title=normalized.document.title,
                parser_version=parser_version,
                chunker_version=self.chunker_version,
                embedding_model=self._embedding_provider.model_name,
                embedding_dimension=self._embedding_provider.dimension,
                chunk_ids=new_chunk_ids,
                structure_quality=structure_quality,
                section_count=len(normalized.sections),
                reindex_recommended=reindex_recommended,
            )
            self._manifest.upsert(record)
            return self._result(
                started,
                document_id=document_id,
                status=IndexStatus.READY,
                chunk_count=len(chunks),
                content_hash=content_hash,
            )
        except Exception as exc:  # noqa: BLE001 - service boundary returns typed failures
            error = str(exc) or exc.__class__.__name__
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
        )

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
