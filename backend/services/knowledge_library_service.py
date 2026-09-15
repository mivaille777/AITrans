from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from backend.rag.config import RagConfig
from backend.rag.document_tree import DocumentTree, DocumentTreeBuilder
from backend.rag.embeddings import EmbeddingProvider
from backend.rag.index_manifest import IndexManifest, IndexManifestRecord
from backend.rag.index_service import IndexDocumentResult, IndexService
from backend.rag.models import NormalizedDocument
from backend.rag.parsers import parse_document

DEFAULT_KNOWLEDGE_MAX_FILE_BYTES = 100 * 1024 * 1024
SUPPORTED_KNOWLEDGE_SUFFIXES = frozenset(
    {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}
)
MAX_SECTION_PREVIEW_CHARS = 60_000


@dataclass(frozen=True, slots=True)
class KnowledgeRuntimeSnapshot:
    enabled: bool
    embedding_provider: str
    embedding_model: str
    embedding_status: str
    device: str
    dimension: int
    vector_store_provider: str
    collection_name: str
    document_count: int
    ready_document_count: int
    indexed_chunk_count: int
    max_file_bytes: int
    allowed_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeSectionSnapshot:
    section_id: str
    heading: str
    level: int
    parent_section_id: str | None
    section_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    block_count: int
    has_equations: bool
    has_tables: bool
    has_figures: bool
    reference_section: bool
    synthetic: bool


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentOutlineSnapshot:
    document_id: str
    title: str
    page_count: int
    sections: tuple[KnowledgeSectionSnapshot, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentSectionSnapshot:
    document_id: str
    section_id: str
    heading: str
    level: int
    section_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    text: str
    truncated: bool


class KnowledgeLibraryService:
    """Safe local-file boundary over indexing and academic workspace metadata."""

    def __init__(
        self,
        *,
        index_service: IndexService,
        manifest: IndexManifest,
        config: RagConfig,
        embedding_provider: EmbeddingProvider,
        allowed_roots: tuple[str | Path, ...] | None = None,
        max_file_bytes: int = DEFAULT_KNOWLEDGE_MAX_FILE_BYTES,
    ) -> None:
        self._index_service = index_service
        self._manifest = manifest
        self._config = config
        self._embedding_provider = embedding_provider
        roots = allowed_roots or (Path.home(),)
        self._allowed_roots = tuple(Path(root).expanduser().resolve() for root in roots)
        self._max_file_bytes = max(1, int(max_file_bytes))
        self._academic_cache: dict[
            str, tuple[str, NormalizedDocument, DocumentTree]
        ] = {}

    def validate_source_path(self, source_path: str | Path) -> Path:
        raw = str(source_path or "").strip()
        if not raw:
            raise ValueError("document path must not be empty")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("document path must be absolute")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("document path must reference a file")
        if not any(resolved.is_relative_to(root) for root in self._allowed_roots):
            raise PermissionError("document path is outside allowed knowledge roots")
        if resolved.suffix.lower() not in SUPPORTED_KNOWLEDGE_SUFFIXES:
            raise ValueError(
                f"unsupported document type: {resolved.suffix.lower() or '<none>'}"
            )
        if resolved.stat().st_size > self._max_file_bytes:
            raise ValueError(
                f"document exceeds the maximum size of {self._max_file_bytes} bytes"
            )
        return resolved

    def import_document(self, source_path: str | Path) -> IndexDocumentResult:
        result = self._index_service.index_document(
            self.validate_source_path(source_path)
        )
        self._academic_cache.pop(result.document_id, None)
        return result

    def list_documents(self) -> list[IndexManifestRecord]:
        return self._manifest.list_records()

    def get_document(self, document_id: str) -> IndexManifestRecord | None:
        return self._manifest.get(str(document_id or "").strip())

    def reindex_document(self, document_id: str) -> IndexDocumentResult | None:
        record = self.get_document(document_id)
        if record is None:
            return None
        path = self.validate_source_path(self._path_from_file_uri(record.source_uri))
        result = self._index_service.reindex_document(path)
        self._academic_cache.pop(record.document_id, None)
        return result

    def delete_document(self, document_id: str) -> bool:
        normalized_id = str(document_id or "").strip()
        deleted = self._index_service.delete_document(normalized_id)
        if deleted:
            self._academic_cache.pop(normalized_id, None)
        return deleted

    def get_document_outline(
        self,
        document_id: str,
    ) -> KnowledgeDocumentOutlineSnapshot | None:
        loaded = self._load_academic_document(document_id)
        if loaded is None:
            return None
        record, normalized, tree = loaded
        sections = tuple(self._section_snapshot(section) for section in tree.sections)
        return KnowledgeDocumentOutlineSnapshot(
            document_id=record.document_id,
            title=normalized.document.title or record.title,
            page_count=len(normalized.pages),
            sections=sections,
        )

    def get_document_section(
        self,
        document_id: str,
        section_id: str,
    ) -> KnowledgeDocumentSectionSnapshot | None:
        loaded = self._load_academic_document(document_id)
        if loaded is None:
            return None
        record, normalized, tree = loaded
        normalized_section_id = str(section_id or "").strip()
        section = next(
            (item for item in tree.sections if item.node_id == normalized_section_id),
            None,
        )
        if section is None:
            return None
        raw_text = normalized.text[section.start_char : section.end_char].strip()
        truncated = len(raw_text) > MAX_SECTION_PREVIEW_CHARS
        text = raw_text[:MAX_SECTION_PREVIEW_CHARS]
        snapshot = self._section_snapshot(section)
        return KnowledgeDocumentSectionSnapshot(
            document_id=record.document_id,
            section_id=section.node_id,
            heading=section.heading,
            level=section.level,
            section_path=section.section_path,
            page_start=snapshot.page_start,
            page_end=snapshot.page_end,
            text=text,
            truncated=truncated,
        )

    def runtime(self) -> KnowledgeRuntimeSnapshot:
        records = self.list_documents()
        embedding_runtime = getattr(self._embedding_provider, "runtime", None)
        status = getattr(embedding_runtime, "status", "uninitialized")
        status_value = getattr(status, "value", status)
        device = str(
            getattr(embedding_runtime, "device", self._config.embedding.device)
            or self._config.embedding.device
        )
        return KnowledgeRuntimeSnapshot(
            enabled=self._config.enabled,
            embedding_provider=self._config.embedding.provider,
            embedding_model=self._embedding_provider.model_name,
            embedding_status=str(status_value or "uninitialized"),
            device=device,
            dimension=self._embedding_provider.dimension,
            vector_store_provider=self._config.vector_store.provider,
            collection_name=self._config.vector_store.collection_name,
            document_count=len(records),
            ready_document_count=sum(
                record.status.value == "ready" for record in records
            ),
            indexed_chunk_count=sum(len(record.chunk_ids) for record in records),
            max_file_bytes=self._max_file_bytes,
            allowed_roots=tuple(str(root) for root in self._allowed_roots),
        )

    def _load_academic_document(
        self,
        document_id: str,
    ) -> tuple[IndexManifestRecord, NormalizedDocument, DocumentTree] | None:
        record = self.get_document(document_id)
        if record is None:
            return None
        cached = self._academic_cache.get(record.document_id)
        if cached is not None and cached[0] == record.content_hash:
            return record, cached[1], cached[2]

        path = self.validate_source_path(self._path_from_file_uri(record.source_uri))
        # The outline must use the same immutable parsing profile as indexing;
        # otherwise a Docling-indexed PDF is misleadingly displayed as one
        # synthetic pypdf section in the desktop UI.
        normalized = parse_document(
            path,
            advanced_config=self._config.advanced_parsing,
        )
        normalized = normalized.model_copy(
            update={
                "document": normalized.document.model_copy(
                    update={
                        "document_id": record.document_id,
                        "source_uri": record.source_uri,
                    }
                )
            }
        )
        tree = DocumentTreeBuilder.build(normalized)
        self._academic_cache[record.document_id] = (
            record.content_hash,
            normalized,
            tree,
        )
        return record, normalized, tree

    @staticmethod
    def _section_snapshot(section) -> KnowledgeSectionSnapshot:
        page_values = [
            page
            for paragraph in section.paragraphs
            for page in (paragraph.page_start, paragraph.page_end)
            if page is not None
        ]
        block_types = {paragraph.block_type for paragraph in section.paragraphs}
        return KnowledgeSectionSnapshot(
            section_id=section.node_id,
            heading=section.heading,
            level=section.level,
            parent_section_id=section.parent_section_id,
            section_path=section.section_path,
            page_start=min(page_values) if page_values else None,
            page_end=max(page_values) if page_values else None,
            block_count=len(section.paragraphs),
            has_equations="equation" in block_types,
            has_tables=bool({"table", "table_caption"} & block_types),
            has_figures="figure_caption" in block_types,
            reference_section=bool(section.metadata.get("reference_section")),
            synthetic=section.synthetic,
        )

    @staticmethod
    def _path_from_file_uri(source_uri: str) -> Path:
        parsed = urlparse(source_uri)
        if parsed.scheme != "file":
            raise ValueError("indexed document source is not a local file URI")
        path = url2pathname(unquote(parsed.path))
        if os.name == "nt" and len(path) >= 3 and path[0] in "/\\" and path[2] == ":":
            path = path[1:]
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        return Path(path)


__all__ = [
    "DEFAULT_KNOWLEDGE_MAX_FILE_BYTES",
    "MAX_SECTION_PREVIEW_CHARS",
    "SUPPORTED_KNOWLEDGE_SUFFIXES",
    "KnowledgeDocumentOutlineSnapshot",
    "KnowledgeDocumentSectionSnapshot",
    "KnowledgeLibraryService",
    "KnowledgeRuntimeSnapshot",
    "KnowledgeSectionSnapshot",
]
