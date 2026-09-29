from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from backend.rag.exceptions import RagInvariantError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.sparse.bm25 import BM25Index
from backend.rag.sparse.tokenizer import SparseTokenizer
from backend.rag.stores.base import VectorSearchFilter, is_reference_chunk
from backend.rag.structure_retrieval import section_match_priority


@runtime_checkable
class SparseRetriever(Protocol):
    def index_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        generation_id: str | None = None,
    ) -> None: ...

    def search(
        self,
        query: str,
        top_k: int,
        filters: VectorSearchFilter | None = None,
        *,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]: ...

    def search_sections(
        self,
        headings: tuple[str, ...],
        top_k: int,
        filters: VectorSearchFilter | None = None,
        *,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]: ...

    def section_neighbors(
        self,
        anchor: DocumentChunk,
        radius: int,
        *,
        generation_id: str | None = None,
    ) -> list[DocumentChunk]: ...

    def delete_document(
        self,
        document_id: str,
        *,
        generation_id: str | None = None,
    ) -> None: ...

    def rebuild(
        self,
        chunks: list[DocumentChunk],
        *,
        generation_id: str | None = None,
    ) -> None: ...

    def list_chunks(
        self,
        *,
        generation_id: str | None = None,
    ) -> list[DocumentChunk]: ...

    def get_chunk(
        self,
        chunk_id: str,
        *,
        generation_id: str | None = None,
    ) -> DocumentChunk | None: ...


class _SparseData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    chunks: dict[str, DocumentChunk] = Field(default_factory=dict)


class BM25SparseRetriever:
    def __init__(
        self,
        path: str | Path = "config/rag/bm25_index.json",
        *,
        tokenizer: SparseTokenizer | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._path = Path(path).expanduser().resolve()
        self._tokenizer = tokenizer or SparseTokenizer()
        self._index = BM25Index(k1=k1, b=b)
        self._data = self._load()
        self._rebuild_index()

    def index_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        generation_id: str | None = None,
    ) -> None:
        normalized_generation = self._normalize_generation_id(generation_id)
        additions: dict[str, DocumentChunk] = {}
        for chunk in chunks:
            chunk_generation = self._chunk_generation(chunk)
            if (
                normalized_generation
                and chunk_generation
                and (normalized_generation != chunk_generation)
            ):
                raise RagInvariantError(
                    "chunk generation metadata does not match generation_id"
                )
            effective_generation = normalized_generation or chunk_generation
            stored_chunk = self._with_generation(chunk, effective_generation)
            storage_key = self._storage_key(chunk.chunk_id, effective_generation)
            existing = additions.get(storage_key) or self._data.chunks.get(storage_key)
            if existing and (
                existing.chunk_id != stored_chunk.chunk_id
                or self._chunk_generation(existing) != effective_generation
            ):
                raise RagInvariantError("sparse generation storage key collision")
            additions[storage_key] = stored_chunk
        self._data.chunks.update(additions)
        self._rebuild_index()
        self._save()

    def search(
        self,
        query: str,
        top_k: int,
        filters: VectorSearchFilter | None = None,
        *,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        normalized_generation = self._normalize_generation_id(generation_id)
        query_tokens = self._tokenizer.tokenize(query)
        if not query_tokens:
            return []
        scores = self._index.score(query_tokens)
        scores = {
            chunk_id: score
            for chunk_id, score in scores.items()
            if self._matches_filter(self._data.chunks[chunk_id], filters)
            and (
                active_generations is not None
                and normalized_generation is None
                or self._matches_generation(
                    self._data.chunks[chunk_id], normalized_generation
                )
            )
            and self._matches_active_generation(
                self._data.chunks[chunk_id], active_generations
            )
        }
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
        return [
            RetrievalCandidate(
                chunk=self._data.chunks[chunk_id].model_copy(deep=True),
                sparse_score=score,
                rank=rank,
            )
            for rank, (chunk_id, score) in enumerate(ranked, start=1)
        ]

    def search_sections(
        self,
        headings: tuple[str, ...],
        top_k: int,
        filters: VectorSearchFilter | None = None,
        *,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        normalized_generation = self._normalize_generation_id(generation_id)
        if not any(str(item).strip() for item in headings):
            return []

        normalized_headings = " ".join(headings).casefold()
        effective_filters = filters
        if (
            (
                "reference" in normalized_headings
                or "bibliography" in normalized_headings
            )
            and filters is not None
            and filters.exclude_references
        ):
            effective_filters = filters.model_copy(update={"exclude_references": False})

        matches: list[tuple[int, DocumentChunk]] = []
        for chunk in self._data.chunks.values():
            if not self._matches_filter(chunk, effective_filters):
                continue
            if not (
                active_generations is not None and normalized_generation is None
            ) and not self._matches_generation(chunk, normalized_generation):
                continue
            if not self._matches_active_generation(chunk, active_generations):
                continue
            priority = section_match_priority(
                RetrievalCandidate(chunk=chunk),
                headings,
            )
            if priority:
                matches.append((priority, chunk))

        matches.sort(
            key=lambda item: (
                -item[0],
                item[1].document_id,
                item[1].page_number if item[1].page_number is not None else 10**9,
                item[1].chunk_index,
                item[1].chunk_id,
            )
        )
        return [
            RetrievalCandidate(
                chunk=chunk.model_copy(deep=True),
                sparse_score=float(priority),
                rank=rank,
                metadata={"structural_section_match": True},
            )
            for rank, (priority, chunk) in enumerate(matches[:top_k], start=1)
        ]

    def section_neighbors(
        self,
        anchor: DocumentChunk,
        radius: int,
        *,
        generation_id: str | None = None,
    ) -> list[DocumentChunk]:
        """Return a bounded document-order neighborhood inside one leaf section."""

        if radius < 0:
            raise ValueError("section neighbor radius must not be negative")
        normalized_generation = self._normalize_generation_id(generation_id)
        anchor_generation = self._chunk_generation(anchor)
        if (
            normalized_generation
            and anchor_generation
            and (normalized_generation != anchor_generation)
        ):
            raise RagInvariantError("anchor generation does not match generation_id")
        normalized_generation = normalized_generation or self._normalize_generation_id(
            anchor_generation
        )
        stored_anchor = self._data.chunks.get(
            self._storage_key(anchor.chunk_id, normalized_generation), anchor
        )
        section_path = tuple(
            item.strip() for item in stored_anchor.section_path if item.strip()
        )
        if not section_path:
            return [stored_anchor.model_copy(deep=True)]

        section_chunks = [
            chunk
            for chunk in self._data.chunks.values()
            if chunk.document_id == stored_anchor.document_id
            and self._matches_generation(chunk, normalized_generation)
            and tuple(item.strip() for item in chunk.section_path if item.strip())
            == section_path
        ]
        section_chunks.sort(key=lambda chunk: (chunk.chunk_index, chunk.chunk_id))
        anchor_position = next(
            (
                index
                for index, chunk in enumerate(section_chunks)
                if chunk.chunk_id == stored_anchor.chunk_id
            ),
            None,
        )
        if anchor_position is None:
            return [stored_anchor.model_copy(deep=True)]
        start = max(0, anchor_position - radius)
        end = min(len(section_chunks), anchor_position + radius + 1)
        return [chunk.model_copy(deep=True) for chunk in section_chunks[start:end]]

    def delete_document(
        self,
        document_id: str,
        *,
        generation_id: str | None = None,
    ) -> None:
        normalized_generation = self._normalize_generation_id(generation_id)
        self._data.chunks = {
            storage_key: chunk
            for storage_key, chunk in self._data.chunks.items()
            if chunk.document_id != document_id
            or (
                normalized_generation is not None
                and self._chunk_generation(chunk) != normalized_generation
            )
        }
        self._rebuild_index()
        self._save()

    def rebuild(
        self,
        chunks: list[DocumentChunk],
        *,
        generation_id: str | None = None,
    ) -> None:
        normalized_generation = self._normalize_generation_id(generation_id)
        rebuilt_chunks: dict[str, DocumentChunk] = {}
        if normalized_generation is not None:
            rebuilt_chunks = {
                key: chunk
                for key, chunk in self._data.chunks.items()
                if self._chunk_generation(chunk) != normalized_generation
            }
        for chunk in chunks:
            chunk_generation = self._chunk_generation(chunk)
            if (
                normalized_generation
                and chunk_generation
                and (normalized_generation != chunk_generation)
            ):
                raise RagInvariantError(
                    "chunk generation metadata does not match generation_id"
                )
            effective_generation = normalized_generation or chunk_generation
            stored_chunk = self._with_generation(chunk, effective_generation)
            storage_key = self._storage_key(chunk.chunk_id, effective_generation)
            existing = rebuilt_chunks.get(storage_key)
            if existing and existing.chunk_id != stored_chunk.chunk_id:
                raise RagInvariantError("sparse generation storage key collision")
            rebuilt_chunks[storage_key] = stored_chunk
        self._data.chunks = rebuilt_chunks
        self._rebuild_index()
        self._save()

    def list_chunks(
        self,
        *,
        generation_id: str | None = None,
    ) -> list[DocumentChunk]:
        """Return the persisted chunk catalogue without exposing private state."""

        normalized_generation = self._normalize_generation_id(generation_id)
        chunks = [
            chunk
            for chunk in self._data.chunks.values()
            if normalized_generation is None
            or self._chunk_generation(chunk) == normalized_generation
        ]
        return [
            chunk.model_copy(deep=True)
            for chunk in sorted(
                chunks,
                key=lambda item: (
                    item.document_id,
                    self._chunk_generation(item) or "",
                    item.page_number if item.page_number is not None else 10**9,
                    item.chunk_index,
                    item.chunk_id,
                ),
            )
        ]

    def get_chunk(
        self,
        chunk_id: str,
        *,
        generation_id: str | None = None,
    ) -> DocumentChunk | None:
        normalized_chunk_id = str(chunk_id or "").strip()
        normalized_generation = self._normalize_generation_id(generation_id)
        chunk = self._data.chunks.get(
            self._storage_key(normalized_chunk_id, normalized_generation)
        )
        return chunk.model_copy(deep=True) if chunk is not None else None

    @staticmethod
    def _normalize_generation_id(generation_id: str | None) -> str | None:
        if generation_id is None:
            return None
        normalized = str(generation_id).strip()
        if not normalized:
            raise RagInvariantError("generation_id must not be empty")
        return normalized

    @staticmethod
    def _chunk_generation(chunk: DocumentChunk) -> str | None:
        generation = str(chunk.metadata.get("index_generation") or "").strip()
        return generation or None

    @staticmethod
    def _storage_key(chunk_id: str, generation_id: str | None) -> str:
        if generation_id is None:
            return chunk_id
        return f"\x00generation:{len(generation_id)}:{generation_id}:{chunk_id}"

    @staticmethod
    def _with_generation(
        chunk: DocumentChunk,
        generation_id: str | None,
    ) -> DocumentChunk:
        copied = chunk.model_copy(deep=True)
        if generation_id is None:
            return copied
        metadata = dict(copied.metadata)
        metadata["index_generation"] = generation_id
        return copied.model_copy(update={"metadata": metadata})

    @classmethod
    def _matches_generation(
        cls,
        chunk: DocumentChunk,
        generation_id: str | None,
    ) -> bool:
        chunk_generation = cls._chunk_generation(chunk)
        return (
            chunk_generation is None
            if generation_id is None
            else chunk_generation == generation_id
        )

    @classmethod
    def _matches_active_generation(
        cls,
        chunk: DocumentChunk,
        active_generations: Mapping[str, str | None] | None,
    ) -> bool:
        if active_generations is None:
            return True
        return (
            chunk.document_id in active_generations
            and cls._chunk_generation(chunk) == active_generations[chunk.document_id]
        )

    def _rebuild_index(self) -> None:
        self._index.rebuild(
            {
                chunk_id: self._tokenizer.tokenize(self._search_text(chunk))
                for chunk_id, chunk in self._data.chunks.items()
            }
        )

    @staticmethod
    def _search_text(chunk: DocumentChunk) -> str:
        special_labels = chunk.metadata.get("special_labels", [])
        if not isinstance(special_labels, list):
            special_labels = []
        parts = [
            chunk.title.strip(),
            " > ".join(item.strip() for item in chunk.section_path if item.strip()),
            chunk.section_heading.strip(),
            chunk.chunk_type.strip(),
            " ".join(str(item).strip() for item in special_labels if str(item).strip()),
            chunk.text,
        ]
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _matches_filter(
        chunk: DocumentChunk,
        filters: VectorSearchFilter | None,
    ) -> bool:
        if filters is None:
            return True
        if filters.document_ids and chunk.document_id not in filters.document_ids:
            return False
        if (
            filters.source_kind
            and chunk.metadata.get("source_kind") != filters.source_kind
        ):
            return False
        if filters.language and chunk.language != filters.language:
            return False
        if filters.exclude_references and is_reference_chunk(chunk):
            return False
        return all(
            chunk.metadata.get(key) == value for key, value in filters.metadata.items()
        )

    def _load(self) -> _SparseData:
        if not self._path.exists():
            return _SparseData()
        try:
            return _SparseData.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise RagInvariantError(f"failed to load BM25 index: {self._path}") from exc

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(self._data.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self._path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise RagInvariantError(
                f"failed to persist BM25 index: {self._path}"
            ) from exc


__all__ = ["BM25SparseRetriever", "SparseRetriever"]
