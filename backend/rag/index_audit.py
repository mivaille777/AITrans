from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.rag.exceptions import RagInvariantError

_STORE_NAMES = ("manifest", "bm25", "vector")


class IndexAuditError(RagInvariantError):
    """Raised when a required index catalogue cannot be read safely."""


class ManifestReader(Protocol):
    def list_records(self) -> list[Any]: ...


class SparseReader(Protocol):
    def list_chunks(self) -> list[Any]: ...


class IndexAuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["warning", "error"]
    store: str = ""
    document_id: str = ""
    chunk_ids: list[str] = Field(default_factory=list)
    message: str


class IndexAuditStoreSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    generation_tagged_chunk_count: int = Field(ge=0)
    generation_unknown_chunk_count: int = Field(ge=0)
    generation_values: list[str] = Field(default_factory=list)


class IndexAuditDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    manifest_status: str = ""
    missing_chunk_ids: dict[str, list[str]] = Field(default_factory=dict)
    generation_by_store: dict[str, list[str]] = Field(default_factory=dict)
    generation_mismatch_chunk_ids: list[str] = Field(default_factory=list)


class IndexAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["consistent", "incomplete", "divergent"]
    chunk_ids_equal: bool
    document_ids_equal: bool
    generation_status: Literal["consistent", "incomplete", "unavailable", "divergent"]
    stores: dict[str, IndexAuditStoreSummary]
    documents: list[IndexAuditDocument] = Field(default_factory=list)
    findings: list[IndexAuditFinding] = Field(default_factory=list)


class _StoreState:
    def __init__(self) -> None:
        self.chunk_ids_by_document: dict[str, set[str]] = defaultdict(set)
        self.generations_by_chunk: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.chunk_ids_by_document_generation: dict[tuple[str, str], set[str]] = (
            defaultdict(set)
        )
        self.untagged_chunk_ids_by_document: dict[str, set[str]] = defaultdict(set)
        self.manifest_status_by_document: dict[str, str] = {}
        self.invalid_vector_points = 0

    def add_document(self, document_id: str) -> None:
        self.chunk_ids_by_document.setdefault(document_id, set())

    @property
    def chunk_count(self) -> int:
        return sum(
            len(chunk_ids)
            for chunk_ids in self.chunk_ids_by_document_generation.values()
        ) + sum(
            len(chunk_ids) for chunk_ids in self.untagged_chunk_ids_by_document.values()
        )

    @property
    def generation_values(self) -> set[str]:
        return {
            generation
            for generations in self.generations_by_chunk.values()
            for generation in generations
        }

    @property
    def generation_tagged_chunk_count(self) -> int:
        return sum(
            len(chunk_ids)
            for chunk_ids in self.chunk_ids_by_document_generation.values()
        )

    def add_chunk(self, document_id: str, chunk_id: str, generation: str = "") -> None:
        self.chunk_ids_by_document[document_id].add(chunk_id)
        if generation:
            self.chunk_ids_by_document_generation[(document_id, generation)].add(
                chunk_id
            )
            self.generations_by_chunk[(document_id, chunk_id)].add(generation)
        else:
            self.untagged_chunk_ids_by_document[document_id].add(chunk_id)


def audit_index_consistency(
    *,
    manifest: ManifestReader | None,
    sparse_retriever: SparseReader | None,
    vector_store: Any | None,
    page_size: int = 512,
) -> IndexAuditReport:
    """Read and compare document, chunk, and generation catalogues.

    Read public chunk catalogues without creating or mutating collections.
    """

    missing = [
        name
        for name, value in (
            ("manifest", manifest),
            ("BM25", sparse_retriever),
            ("vector store", vector_store),
        )
        if value is None
    ]
    if missing:
        raise IndexAuditError(
            "required index catalogue is missing: " + ", ".join(missing)
        )
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    states = {name: _StoreState() for name in _STORE_NAMES}
    _read_manifest(manifest, states["manifest"])
    _read_sparse(sparse_retriever, states["bm25"])
    _read_vector(vector_store, states["vector"], page_size=page_size)
    return _build_report(states)


def _read_manifest(manifest: ManifestReader, state: _StoreState) -> None:
    list_records = getattr(manifest, "list_records", None)
    if not callable(list_records):
        raise IndexAuditError("manifest catalogue does not expose list_records()")
    try:
        records = list_records()
    except Exception as exc:
        raise IndexAuditError("failed to read manifest catalogue") from exc

    for record in records:
        document_id = str(getattr(record, "document_id", "") or "").strip()
        if not document_id:
            raise IndexAuditError("manifest record has no document_id")
        status = getattr(record, "status", "")
        state.manifest_status_by_document[document_id] = str(
            getattr(status, "value", status) or ""
        )
        # Keep empty manifest documents visible in the document-level diff.
        state.add_document(document_id)
        chunk_ids = getattr(record, "chunk_ids", None)
        if not isinstance(chunk_ids, (list, tuple, set)):
            raise IndexAuditError(
                f"manifest record for {document_id!r} has no chunk ID catalogue"
            )
        generation = _generation(
            getattr(record, "index_generation", None)
            or getattr(record, "generation_id", None)
            or getattr(record, "generation", None)
        )
        for raw_chunk_id in chunk_ids:
            chunk_id = str(raw_chunk_id or "").strip()
            if not chunk_id:
                raise IndexAuditError(
                    f"manifest record for {document_id!r} has an empty chunk ID"
                )
            state.add_chunk(document_id, chunk_id, generation)

    list_generations = getattr(manifest, "list_generations", None)
    if callable(list_generations):
        for document_id in sorted(state.manifest_status_by_document):
            try:
                generations = list_generations(document_id)
            except Exception as exc:
                raise IndexAuditError(
                    f"failed to read manifest generations for {document_id!r}"
                ) from exc
            for generation_record in generations:
                generation_status = getattr(generation_record, "status", "")
                if getattr(generation_status, "value", generation_status) == "failed":
                    # A failed generation is expected to be physically rolled
                    # back; surviving points will still appear as store-only IDs.
                    continue
                generation_id = _generation(
                    getattr(generation_record, "generation_id", None)
                )
                if not generation_id:
                    raise IndexAuditError(
                        f"manifest generation for {document_id!r} has no generation ID"
                    )
                generation_chunk_ids = getattr(generation_record, "chunk_ids", None)
                if not isinstance(generation_chunk_ids, (list, tuple, set)):
                    raise IndexAuditError(
                        f"manifest generation {document_id!r}/{generation_id!r} "
                        "has no chunk ID catalogue"
                    )
                for raw_chunk_id in generation_chunk_ids:
                    chunk_id = str(raw_chunk_id or "").strip()
                    if not chunk_id:
                        raise IndexAuditError(
                            f"manifest generation {document_id!r}/{generation_id!r} "
                            "has an empty chunk ID"
                        )
                    state.add_chunk(document_id, chunk_id, generation_id)


def _read_sparse(sparse_retriever: SparseReader, state: _StoreState) -> None:
    list_chunks = getattr(sparse_retriever, "list_chunks", None)
    if not callable(list_chunks):
        raise IndexAuditError("BM25 catalogue does not expose list_chunks()")
    try:
        chunks = list_chunks()
    except Exception as exc:
        raise IndexAuditError("failed to read BM25 catalogue") from exc
    for chunk in chunks:
        document_id, chunk_id = _chunk_identity(chunk, "BM25")
        generation = _generation(_chunk_generation_value(chunk))
        state.add_chunk(document_id, chunk_id, generation)


def _read_vector(vector_store: Any, state: _StoreState, *, page_size: int) -> None:
    repository = getattr(vector_store, "repository", None)
    collection_name = str(getattr(vector_store, "collection_name", "") or "")
    if repository is not None and repository.collection(collection_name) is None:
        raise IndexAuditError(f"vector collection {collection_name!r} is missing")
    try:
        for chunk in vector_store.list_chunks():
            document_id, chunk_id = _chunk_identity(chunk, "vector")
            state.add_chunk(document_id, chunk_id, _generation(_chunk_generation_value(chunk)))
    except Exception as exc:
        raise IndexAuditError(f"failed to read vector collection {collection_name!r}") from exc


def _chunk_identity(chunk: Any, store: str) -> tuple[str, str]:
    document_id = str(getattr(chunk, "document_id", "") or "").strip()
    chunk_id = str(getattr(chunk, "chunk_id", "") or "").strip()
    if not document_id or not chunk_id:
        raise IndexAuditError(f"{store} catalogue contains a chunk without IDs")
    return document_id, chunk_id


def _chunk_generation_value(chunk: Any) -> Any:
    if isinstance(chunk, dict):
        metadata = chunk.get("metadata")
        return (
            chunk.get("index_generation")
            or chunk.get("generation_id")
            or chunk.get("generation")
            or _metadata_generation(metadata)
        )
    metadata = getattr(chunk, "metadata", None)
    return (
        getattr(chunk, "index_generation", None)
        or getattr(chunk, "generation_id", None)
        or getattr(chunk, "generation", None)
        or _metadata_generation(metadata)
    )


def _metadata_generation(metadata: Any) -> Any:
    if not isinstance(metadata, dict):
        return None
    return (
        metadata.get("index_generation")
        or metadata.get("generation_id")
        or metadata.get("generation")
    )


def _generation(value: Any) -> str:
    return str(value or "").strip()


def _build_report(states: dict[str, _StoreState]) -> IndexAuditReport:
    document_ids_by_store = {
        name: set(state.chunk_ids_by_document) for name, state in states.items()
    }
    all_document_ids = set().union(*document_ids_by_store.values())
    document_ids_equal = (
        len({frozenset(ids) for ids in document_ids_by_store.values()}) == 1
    )
    findings: list[IndexAuditFinding] = []
    document_reports: list[IndexAuditDocument] = []
    chunk_ids_equal = True
    generation_mismatch = False
    generation_incomplete = False

    for document_id in sorted(all_document_ids):
        ids_by_store = {
            name: states[name].chunk_ids_by_document.get(document_id, set())
            for name in _STORE_NAMES
        }
        all_chunk_ids = set().union(*ids_by_store.values())
        missing_chunk_ids = {
            name: sorted(all_chunk_ids - ids_by_store[name]) for name in _STORE_NAMES
        }
        document_chunks_equal = (
            len({frozenset(chunk_ids) for chunk_ids in ids_by_store.values()}) == 1
        )
        chunk_ids_equal = chunk_ids_equal and document_chunks_equal
        if not document_chunks_equal:
            for name, missing_ids in missing_chunk_ids.items():
                if missing_ids:
                    findings.append(
                        IndexAuditFinding(
                            code="CHUNK_ID_DIFFERENCE",
                            severity="error",
                            store=name,
                            document_id=document_id,
                            chunk_ids=missing_ids,
                            message=f"{name} is missing chunk IDs present in another store",
                        )
                    )

        generations_by_store: dict[str, list[str]] = {}
        chunk_mismatch_ids: list[str] = []
        for chunk_id in sorted(all_chunk_ids):
            generations = {
                name: states[name].generations_by_chunk.get(
                    (document_id, chunk_id), set()
                )
                for name in _STORE_NAMES
            }
            for name, values in generations.items():
                generations_by_store.setdefault(name, set()).update(values)
            if all(chunk_id in ids_by_store[name] for name in _STORE_NAMES):
                known_values = {frozenset(values) for values in generations.values()}
                if len(known_values) > 1:
                    generation_mismatch = True
                    chunk_mismatch_ids.append(chunk_id)
                elif not all(generations[name] for name in _STORE_NAMES):
                    generation_incomplete = True
        if chunk_mismatch_ids:
            findings.append(
                IndexAuditFinding(
                    code="GENERATION_DIFFERENCE",
                    severity="error",
                    document_id=document_id,
                    chunk_ids=chunk_mismatch_ids,
                    message="stores report different generation IDs for the same chunk",
                )
            )

        missing_docs = [
            name
            for name in _STORE_NAMES
            if document_id not in document_ids_by_store[name]
        ]
        if missing_docs:
            findings.append(
                IndexAuditFinding(
                    code="DOCUMENT_ID_DIFFERENCE",
                    severity="error",
                    document_id=document_id,
                    message="document is missing from: " + ", ".join(missing_docs),
                )
            )
        status = states["manifest"].manifest_status_by_document.get(document_id, "")
        if status and status != "ready":
            findings.append(
                IndexAuditFinding(
                    code="MANIFEST_NOT_READY",
                    severity="warning",
                    store="manifest",
                    document_id=document_id,
                    message=f"manifest status is {status!r}",
                )
            )
        document_reports.append(
            IndexAuditDocument(
                document_id=document_id,
                manifest_status=status,
                missing_chunk_ids=missing_chunk_ids,
                generation_by_store={
                    name: sorted(values)
                    for name, values in generations_by_store.items()
                },
                generation_mismatch_chunk_ids=chunk_mismatch_ids,
            )
        )

    if not document_ids_equal:
        findings.append(
            IndexAuditFinding(
                code="DOCUMENT_ID_DIFFERENCE",
                severity="error",
                message="document ID catalogues differ across manifest, BM25, and vector store",
            )
        )

    generation_tagged_count = sum(
        state.generation_tagged_chunk_count for state in states.values()
    )
    all_chunk_count = sum(state.chunk_count for state in states.values())
    if any(state.invalid_vector_points for state in states.values()):
        count = states["vector"].invalid_vector_points
        findings.append(
            IndexAuditFinding(
                code="INVALID_VECTOR_PAYLOAD",
                severity="error",
                store="vector",
                message=f"{count} points are missing document_id or chunk_id payload fields",
            )
        )
    if generation_mismatch:
        generation_status: Literal[
            "consistent", "incomplete", "unavailable", "divergent"
        ] = "divergent"
    elif not generation_tagged_count:
        generation_status = "unavailable"
        findings.append(
            IndexAuditFinding(
                code="GENERATION_METADATA_UNAVAILABLE",
                severity="warning",
                message="none of the three catalogues exposes an index generation ID",
            )
        )
    elif generation_incomplete or generation_tagged_count < all_chunk_count:
        generation_status = "incomplete"
        findings.append(
            IndexAuditFinding(
                code="GENERATION_METADATA_INCOMPLETE",
                severity="warning",
                message="one or more stored chunks lack generation metadata",
            )
        )
    else:
        generation_status = "consistent"

    divergent = not chunk_ids_equal or not document_ids_equal or generation_mismatch
    if divergent:
        status_value: Literal["consistent", "incomplete", "divergent"] = "divergent"
    elif generation_status != "consistent" or states["vector"].invalid_vector_points:
        status_value = "incomplete"
    else:
        status_value = "consistent"

    summaries = {
        name: IndexAuditStoreSummary(
            document_count=len(state.chunk_ids_by_document),
            chunk_count=state.chunk_count,
            generation_tagged_chunk_count=state.generation_tagged_chunk_count,
            generation_unknown_chunk_count=(
                state.chunk_count - state.generation_tagged_chunk_count
            ),
            generation_values=sorted(state.generation_values),
        )
        for name, state in states.items()
    }
    return IndexAuditReport(
        status=status_value,
        chunk_ids_equal=chunk_ids_equal,
        document_ids_equal=document_ids_equal,
        generation_status=generation_status,
        stores=summaries,
        documents=document_reports,
        findings=findings,
    )


__all__ = [
    "IndexAuditDocument",
    "IndexAuditError",
    "IndexAuditFinding",
    "IndexAuditReport",
    "IndexAuditStoreSummary",
    "audit_index_consistency",
]
