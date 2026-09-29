from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from backend.rag.exceptions import RagInvariantError


class IndexStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class IndexGenerationStatus(str, Enum):
    BUILDING = "building"
    VALIDATING = "validating"
    READY = "ready"
    RETIRED = "retired"
    FAILED = "failed"


ACTIVE_INDEX_STATUSES = frozenset(
    {
        IndexStatus.PARSING,
        IndexStatus.CHUNKING,
        IndexStatus.EMBEDDING,
        IndexStatus.INDEXING,
    }
)


class IndexManifestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    content_hash: str = ""
    source_uri: str = ""
    title: str = ""
    parser_version: str = ""
    chunker_version: str = ""
    embedding_model: str = ""
    embedding_dimension: int = Field(default=0, ge=0)
    structure_quality: str = "unknown"
    section_count: int = Field(default=0, ge=0)
    reindex_recommended: bool = False
    chunk_ids: list[str] = Field(default_factory=list)
    generation_id: str = ""
    status: IndexStatus = IndexStatus.PENDING
    indexed_at: datetime | None = None
    error: str = ""


class IndexGenerationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    status: IndexGenerationStatus = IndexGenerationStatus.BUILDING
    chunk_ids: list[str] = Field(min_length=1)
    previous_generation_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validated_at: datetime | None = None
    published_at: datetime | None = None
    error: str = ""


class _ManifestData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    documents: dict[str, IndexManifestRecord] = Field(default_factory=dict)
    generations: dict[str, dict[str, IndexGenerationRecord]] = Field(
        default_factory=dict
    )


class IndexManifest:
    """Small, atomically persisted document index manifest."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()
        self._lock = RLock()
        self._data = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def get(self, document_id: str) -> IndexManifestRecord | None:
        with self._lock:
            record = self._data.documents.get(document_id)
            return record.model_copy(deep=True) if record else None

    def find_by_source_uri(self, source_uri: str) -> IndexManifestRecord | None:
        with self._lock:
            for record in self._data.documents.values():
                if record.source_uri == source_uri:
                    return record.model_copy(deep=True)
        return None

    def list_records(self) -> list[IndexManifestRecord]:
        with self._lock:
            return [
                record.model_copy(deep=True)
                for record in sorted(
                    self._data.documents.values(),
                    key=lambda item: item.document_id,
                )
            ]

    def begin_generation(
        self,
        document_id: str,
        generation_id: str,
        chunk_ids: list[str],
    ) -> IndexGenerationRecord:
        """Record a new immutable generation in the building state."""

        normalized_document_id = str(document_id or "").strip()
        normalized_generation_id = str(generation_id or "").strip()
        normalized_chunk_ids = [str(chunk_id or "").strip() for chunk_id in chunk_ids]
        if not normalized_document_id:
            raise RagInvariantError("generation document_id must not be empty")
        if not normalized_generation_id:
            raise RagInvariantError("generation_id must not be empty")
        if not normalized_chunk_ids or any(
            not chunk_id for chunk_id in normalized_chunk_ids
        ):
            raise RagInvariantError("generation must contain non-empty chunk IDs")
        if len(set(normalized_chunk_ids)) != len(normalized_chunk_ids):
            raise RagInvariantError("generation contains duplicate chunk IDs")

        with self._lock:
            document_generations = self._data.generations.setdefault(
                normalized_document_id, {}
            )
            if normalized_generation_id in document_generations:
                raise RagInvariantError(
                    f"generation already exists: {normalized_document_id}/"
                    f"{normalized_generation_id}"
                )
            current = self._data.documents.get(normalized_document_id)
            previous_generation_id = current.generation_id if current else ""
            record = IndexGenerationRecord(
                document_id=normalized_document_id,
                generation_id=normalized_generation_id,
                chunk_ids=normalized_chunk_ids,
                previous_generation_id=previous_generation_id,
            )
            document_generations[normalized_generation_id] = record
            self._save()
            return record.model_copy(deep=True)

    def validate_generation(
        self,
        document_id: str,
        generation_id: str,
        observed_chunk_ids: list[str] | set[str] | tuple[str, ...],
    ) -> IndexGenerationRecord:
        """Move a building generation to validating after exact ID comparison."""

        with self._lock:
            record = self._get_generation_for_transition(document_id, generation_id)
            self._require_generation_status(record, IndexGenerationStatus.BUILDING)
            observed = {str(chunk_id or "").strip() for chunk_id in observed_chunk_ids}
            expected = set(record.chunk_ids)
            if "" in observed or observed != expected:
                missing = sorted(expected - observed)
                unexpected = sorted(observed - expected)
                raise RagInvariantError(
                    "generation chunk IDs failed validation; "
                    f"missing={missing}, unexpected={unexpected}"
                )
            record.status = IndexGenerationStatus.VALIDATING
            record.validated_at = datetime.now(UTC)
            self._save()
            return record.model_copy(deep=True)

    def publish_generation(
        self,
        document_id: str,
        generation_id: str,
        *,
        manifest_record: IndexManifestRecord | None = None,
    ) -> IndexGenerationRecord:
        """Atomically activate a validated generation and retain its predecessor."""

        with self._lock:
            before_publish = self._data.model_copy(deep=True)
            normalized_document_id = str(document_id or "").strip()
            record = self._get_generation_for_transition(
                normalized_document_id, generation_id
            )
            self._require_generation_status(record, IndexGenerationStatus.VALIDATING)
            if manifest_record is not None and (
                manifest_record.document_id != normalized_document_id
                or manifest_record.chunk_ids != record.chunk_ids
            ):
                raise RagInvariantError(
                    "published manifest record does not match generation identity"
                )
            document_record = self._data.documents.get(normalized_document_id)
            previous_generation_id = (
                document_record.generation_id if document_record else ""
            )
            if previous_generation_id:
                previous = self._data.generations.get(normalized_document_id, {}).get(
                    previous_generation_id
                )
                if (
                    previous is None
                    or previous.status is not IndexGenerationStatus.READY
                ):
                    raise RagInvariantError(
                        "active generation pointer does not reference a READY generation"
                    )
                previous.status = IndexGenerationStatus.RETIRED

            now = datetime.now(UTC)
            record.status = IndexGenerationStatus.READY
            record.previous_generation_id = previous_generation_id
            record.published_at = now
            record.error = ""
            if manifest_record is not None:
                document_record = manifest_record.model_copy(
                    update={
                        "generation_id": record.generation_id,
                        "status": IndexStatus.READY,
                        "indexed_at": now,
                        "error": "",
                    },
                    deep=True,
                )
            elif document_record is None:
                document_record = IndexManifestRecord(
                    document_id=normalized_document_id,
                    chunk_ids=list(record.chunk_ids),
                    generation_id=record.generation_id,
                    status=IndexStatus.READY,
                    indexed_at=now,
                )
            else:
                document_record = document_record.model_copy(
                    update={
                        "chunk_ids": list(record.chunk_ids),
                        "generation_id": record.generation_id,
                        "status": IndexStatus.READY,
                        "indexed_at": now,
                        "error": "",
                    },
                    deep=True,
                )
            self._data.documents[normalized_document_id] = document_record
            try:
                self._save()
            except Exception:
                self._data = before_publish
                raise
            return record.model_copy(deep=True)

    def fail_generation(
        self,
        document_id: str,
        generation_id: str,
        *,
        error: str,
    ) -> IndexGenerationRecord:
        with self._lock:
            record = self._get_generation_for_transition(document_id, generation_id)
            if record.status not in {
                IndexGenerationStatus.BUILDING,
                IndexGenerationStatus.VALIDATING,
            }:
                raise RagInvariantError(
                    f"cannot fail generation in {record.status.value!r} state"
                )
            record.status = IndexGenerationStatus.FAILED
            record.error = str(error or "generation failed")
            self._save()
            return record.model_copy(deep=True)

    def recover_interrupted_generations(self) -> list[str]:
        """Fail persisted build/validation work left behind by a terminated process."""

        with self._lock:
            recovered = self._recover_interrupted_generations_locked()
            if recovered:
                self._save()
            return sorted(recovered)

    def get_generation(
        self,
        document_id: str,
        generation_id: str,
    ) -> IndexGenerationRecord | None:
        with self._lock:
            record = self._data.generations.get(document_id, {}).get(generation_id)
            return record.model_copy(deep=True) if record else None

    def list_generations(self, document_id: str) -> list[IndexGenerationRecord]:
        with self._lock:
            return [
                record.model_copy(deep=True)
                for _, record in sorted(
                    self._data.generations.get(document_id, {}).items()
                )
            ]

    def get_active_generation(self, document_id: str) -> IndexGenerationRecord | None:
        with self._lock:
            document_record = self._data.documents.get(document_id)
            generation_id = document_record.generation_id if document_record else ""
            if not generation_id:
                return None
            generation = self._data.generations.get(document_id, {}).get(generation_id)
            if (
                generation is None
                or generation.status is not IndexGenerationStatus.READY
            ):
                raise RagInvariantError(
                    f"active generation pointer is invalid: {document_id}/{generation_id}"
                )
            return generation.model_copy(deep=True)

    def list_active_generations(self) -> dict[str, str | None]:
        """Return each READY document's published generation (None for legacy)."""

        with self._lock:
            active: dict[str, str | None] = {}
            for document_id, document in self._data.documents.items():
                if document.status is not IndexStatus.READY:
                    continue
                generation_id = document.generation_id.strip()
                if generation_id:
                    generation = self._data.generations.get(document_id, {}).get(
                        generation_id
                    )
                    if (
                        generation is None
                        or generation.status is not IndexGenerationStatus.READY
                    ):
                        raise RagInvariantError(
                            "active generation pointer is invalid: "
                            f"{document_id}/{generation_id}"
                        )
                    active[document_id] = generation_id
                else:
                    active[document_id] = None
            return active

    def upsert(self, record: IndexManifestRecord) -> None:
        with self._lock:
            existing = self._data.documents.get(record.document_id)
            replacement = record.model_copy(deep=True)
            if existing and not replacement.generation_id:
                replacement.generation_id = existing.generation_id
            self._data.documents[record.document_id] = replacement
            self._save()

    def delete(self, document_id: str) -> bool:
        with self._lock:
            removed = self._data.documents.pop(document_id, None) is not None
            if removed:
                self._save()
            return removed

    def mark_status(
        self,
        document_id: str,
        status: IndexStatus,
        *,
        source_uri: str = "",
        error: str = "",
    ) -> IndexManifestRecord:
        with self._lock:
            existing = self._data.documents.get(document_id)
            record = (
                existing.model_copy(deep=True)
                if existing
                else IndexManifestRecord(
                    document_id=document_id,
                    source_uri=source_uri,
                )
            )
            record.status = status
            record.error = error
            if source_uri:
                record.source_uri = source_uri
            self._data.documents[document_id] = record
            self._save()
            return record.model_copy(deep=True)

    def recover_interrupted_operations(self) -> list[str]:
        """Fail persisted in-flight states left behind by a terminated backend.

        Indexing is synchronous inside one backend process and there is no durable
        worker queue that can resume a half-finished parse/embed/index operation.
        Therefore any active status loaded while constructing a fresh runtime is
        necessarily stale. Leaving it active makes the desktop poll forever even
        though no work is running.
        """

        with self._lock:
            recovered: list[str] = []
            for document_id, existing in self._data.documents.items():
                if existing.status not in ACTIVE_INDEX_STATUSES:
                    continue
                interrupted_stage = existing.status.value
                record = existing.model_copy(deep=True)
                record.status = IndexStatus.FAILED
                record.error = (
                    f"Previous indexing run was interrupted during {interrupted_stage}. "
                    "Reindex the document to continue."
                )
                self._data.documents[document_id] = record
                recovered.append(document_id)
            generation_recovered = self._recover_interrupted_generations_locked()
            if recovered or generation_recovered:
                self._save()
            return recovered

    def _load(self) -> _ManifestData:
        if not self._path.exists():
            return _ManifestData()
        try:
            return _ManifestData.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise RagInvariantError(
                f"failed to read RAG index manifest: {self._path}"
            ) from exc

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._data.model_dump_json(indent=2)
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
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self._path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise RagInvariantError(
                f"failed to persist RAG index manifest: {self._path}"
            ) from exc

    def _get_generation_for_transition(
        self,
        document_id: str,
        generation_id: str,
    ) -> IndexGenerationRecord:
        normalized_document_id = str(document_id or "").strip()
        normalized_generation_id = str(generation_id or "").strip()
        record = self._data.generations.get(normalized_document_id, {}).get(
            normalized_generation_id
        )
        if record is None:
            raise RagInvariantError(
                f"generation not found: {normalized_document_id}/"
                f"{normalized_generation_id}"
            )
        return record

    def _recover_interrupted_generations_locked(self) -> list[str]:
        recovered: list[str] = []
        for document_id, generations in self._data.generations.items():
            for generation_id, record in generations.items():
                if record.status not in {
                    IndexGenerationStatus.BUILDING,
                    IndexGenerationStatus.VALIDATING,
                }:
                    continue
                interrupted_stage = record.status.value
                record.status = IndexGenerationStatus.FAILED
                record.error = (
                    "Previous generation operation was interrupted during "
                    f"{interrupted_stage}. Rebuild the generation to continue."
                )
                recovered.append(f"{document_id}:{generation_id}")

            document_record = self._data.documents.get(document_id)
            if document_record is None:
                continue
            active_generation_id = document_record.generation_id
            active_generation = generations.get(active_generation_id)
            if (
                active_generation
                and active_generation.status is IndexGenerationStatus.READY
            ):
                document_record.status = IndexStatus.READY
                document_record.error = ""
            elif (
                not active_generation_id
                and document_record.status in ACTIVE_INDEX_STATUSES
            ):
                document_record.status = IndexStatus.FAILED
                document_record.error = (
                    "Previous generation operation was interrupted. "
                    "Rebuild the generation to continue."
                )
        return recovered

    @staticmethod
    def _require_generation_status(
        record: IndexGenerationRecord,
        required_status: IndexGenerationStatus,
    ) -> None:
        if record.status is not required_status:
            raise RagInvariantError(
                f"generation transition requires {required_status.value!r}; "
                f"got {record.status.value!r}"
            )


def ready_manifest_record(
    *,
    document_id: str,
    content_hash: str,
    source_uri: str,
    title: str,
    parser_version: str,
    chunker_version: str,
    embedding_model: str,
    embedding_dimension: int,
    chunk_ids: list[str],
    structure_quality: str = "unknown",
    section_count: int = 0,
    reindex_recommended: bool = False,
) -> IndexManifestRecord:
    return IndexManifestRecord(
        document_id=document_id,
        content_hash=content_hash,
        source_uri=source_uri,
        title=title,
        parser_version=parser_version,
        chunker_version=chunker_version,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        structure_quality=structure_quality,
        section_count=section_count,
        reindex_recommended=reindex_recommended,
        chunk_ids=chunk_ids,
        status=IndexStatus.READY,
        indexed_at=datetime.now(UTC),
    )


__all__ = [
    "ACTIVE_INDEX_STATUSES",
    "IndexGenerationRecord",
    "IndexGenerationStatus",
    "IndexManifest",
    "IndexManifestRecord",
    "IndexStatus",
    "ready_manifest_record",
]
