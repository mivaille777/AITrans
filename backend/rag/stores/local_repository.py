"""Durable vectors and chunks; FAISS indexes are disposable read caches."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

import numpy as np

from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.models import DocumentChunk

SCHEMA_VERSION = 1


def generation_key(value: str | None, *, allow_empty: bool = False) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or (not value.strip() and not allow_empty):
        raise RagVectorStoreError("generation_id must be a non-empty string")
    return value.strip()


def vector_array(value, dimension: int, *, multivector: bool = False) -> np.ndarray:
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            result = np.array(value, dtype="<f4", order="C", copy=True)
    except (ValueError, TypeError, OverflowError) as exc:
        raise RagVectorStoreError("vector contains a non-numeric value") from exc
    expected_ndim = 2 if multivector else 1
    if result.ndim != expected_ndim or result.shape[-1] != dimension:
        raise RagVectorStoreError(f"vector dimension mismatch: expected {dimension}")
    if multivector and result.shape[0] == 0:
        raise RagVectorStoreError("multivector must contain at least one token vector")
    if not np.isfinite(result).all():
        raise RagVectorStoreError("vector contains non-finite values")
    return result


def normalize_rows(value: np.ndarray) -> np.ndarray:
    # Keep zero vectors compatible with the old local store, without division by zero.
    result = value.copy()
    norms = np.linalg.norm(result.astype(np.float64), axis=-1, keepdims=True)
    np.divide(result, norms, out=result, where=norms != 0)
    return result


@dataclass(frozen=True)
class VectorItem:
    vector_id: int
    chunk: DocumentChunk
    generation: str
    index_version: str
    token_count: int
    vector: np.ndarray | None = None
    coarse: np.ndarray | None = None


class LocalVectorRepository:
    """One writable owner per directory, shared by text and visual adapters."""

    def __init__(self, root: str | Path, *, read_only: bool = False) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "vector_store.sqlite3"
        self.lock = RLock()
        self.read_only = read_only
        self._owner = None
        self._connection = None
        self._closed = False
        if read_only and not self.path.is_file():
            raise RagConfigurationError(f"vector database is missing: {self.path}")
        try:
            if not read_only:
                self.root.mkdir(parents=True, exist_ok=True)
                self._owner = (self.root / "owner.lock").open("a+b")
                self._owner.seek(0, 2)
                if self._owner.tell() == 0:
                    self._owner.write(b"0")
                    self._owner.flush()
                self._owner.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self._owner.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            location = self.path.as_uri() + "?mode=ro" if read_only else str(self.path)
            self._connection = sqlite3.connect(
                location,
                uri=read_only,
                timeout=30,
                check_same_thread=False,
                isolation_level=None,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            if not read_only:
                self._connection.execute("PRAGMA journal_mode=WAL")
                self._connection.execute("PRAGMA synchronous=FULL")
                self._initialize()
            version = self._connection.execute(
                "SELECT schema_version FROM store_meta"
            ).fetchone()
            if version is None or version[0] != SCHEMA_VERSION:
                raise RagConfigurationError(
                    "unsupported vector database schema version"
                )
        except Exception as exc:
            self.close()
            if isinstance(exc, RagConfigurationError):
                raise
            raise RagConfigurationError(
                f"cannot open vector store (another writer may own it): {self.root}"
            ) from exc

    def _initialize(self) -> None:
        if self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='store_meta'"
        ).fetchone():
            versions = self.connection.execute(
                "SELECT schema_version FROM store_meta"
            ).fetchall()
            if len(versions) != 1 or versions[0][0] != SCHEMA_VERSION:
                raise RagConfigurationError(
                    "unsupported vector database schema version"
                )
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS store_meta(schema_version INTEGER NOT NULL, store_uuid TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS collections(
                name TEXT PRIMARY KEY, kind TEXT NOT NULL, dimension INTEGER NOT NULL,
                distance TEXT NOT NULL, fingerprint TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS items(
                vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL REFERENCES collections(name),
                chunk_id TEXT NOT NULL, document_id TEXT NOT NULL, generation TEXT NOT NULL,
                index_version TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
                vector BLOB NOT NULL, token_count INTEGER NOT NULL, coarse BLOB,
                UNIQUE(collection, chunk_id, generation, index_version));
            CREATE INDEX IF NOT EXISTS items_document ON items(collection, document_id, generation);
        """)
        if (
            self.connection.execute("SELECT COUNT(*) FROM store_meta").fetchone()[0]
            == 0
        ):
            self.connection.execute(
                "INSERT INTO store_meta VALUES (?,?)", (SCHEMA_VERSION, uuid4().hex)
            )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None or self._closed:
            raise RagVectorStoreError("vector repository is closed")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            raise RagVectorStoreError("vector repository is read-only")
        with self.lock:
            connection = self.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException as exc:
                connection.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    raise RagVectorStoreError("vector transaction failed and was rolled back") from exc
                raise

    def ensure_collection(
        self, name: str, kind: str, dimension: int, distance: str, fingerprint: str = ""
    ) -> None:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM collections WHERE name=?", (name,)
            ).fetchone()
            if row is not None:
                if (row["kind"], row["dimension"], row["distance"]) != (
                    kind,
                    dimension,
                    distance,
                ):
                    raise RagConfigurationError(
                        "existing vector collection schema mismatch"
                    )
                if (
                    fingerprint
                    and row["fingerprint"]
                    and fingerprint != row["fingerprint"]
                ):
                    raise RagConfigurationError(
                        "existing vector collection embedding fingerprint mismatch; reindex required in a new collection"
                    )
                if fingerprint and not row["fingerprint"]:
                    if self.connection.execute(
                        "SELECT 1 FROM items WHERE collection=? LIMIT 1", (name,)
                    ).fetchone():
                        raise RagConfigurationError(
                            "populated collection has no embedding fingerprint; migrate explicitly"
                        )
                    with self.transaction() as conn:
                        conn.execute(
                            "UPDATE collections SET fingerprint=? WHERE name=?",
                            (fingerprint, name),
                        )
                return
            if self.read_only:
                raise RagConfigurationError(f"vector collection is missing: {name}")
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO collections(name,kind,dimension,distance,fingerprint) VALUES (?,?,?,?,?)",
                    (name, kind, dimension, distance, fingerprint),
                )

    def collection(self, name: str):
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM collections WHERE name=?", (name,)
            ).fetchone()

    def write(
        self,
        name: str,
        values: Sequence[tuple[DocumentChunk, np.ndarray, str, np.ndarray | None]],
        *,
        replace: tuple[str, str, str] | None = None,
    ) -> None:
        schema = self.collection(name)
        if schema is None:
            raise RagVectorStoreError("vector collection is missing")
        prepared = []
        for chunk, vector, version, coarse in values:
            generation = generation_key(
                chunk.metadata.get("index_generation"), allow_empty=True
            )
            if (
                replace is not None
                and (chunk.document_id, generation, version) != replace
            ):
                raise RagVectorStoreError(
                    "replacement identity does not match its batch"
                )
            array = vector_array(
                vector, schema["dimension"], multivector=schema["kind"] == "visual"
            )
            pooled = (
                vector_array(coarse, schema["dimension"])
                if coarse is not None
                else None
            )
            prepared.append((chunk, array, version, pooled))
        with self.transaction() as conn:
            for chunk, vector, version, coarse in prepared:
                generation = generation_key(
                    chunk.metadata.get("index_generation"), allow_empty=True
                )
                previous = conn.execute(
                    "SELECT document_id FROM items WHERE collection=? AND chunk_id=? AND generation=? AND index_version=?",
                    (name, chunk.chunk_id, generation, version),
                ).fetchone()
                if previous is not None and previous[0] != chunk.document_id:
                    raise RagVectorStoreError(
                        "chunk identity belongs to a different document"
                    )
                conn.execute(
                    """INSERT INTO items(collection,chunk_id,document_id,generation,index_version,payload,vector,token_count,coarse)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(collection,chunk_id,generation,index_version)
                    DO UPDATE SET payload=excluded.payload,vector=excluded.vector,token_count=excluded.token_count,coarse=excluded.coarse""",
                    (
                        name,
                        chunk.chunk_id,
                        chunk.document_id,
                        generation,
                        version,
                        chunk.model_dump_json(),
                        vector.astype("<f4", copy=False).tobytes(),
                        vector.shape[0] if vector.ndim == 2 else 1,
                        coarse.astype("<f4", copy=False).tobytes()
                        if coarse is not None
                        else None,
                    ),
                )
            if replace is not None:
                retained = {chunk.chunk_id for chunk, *_ in prepared}
                existing = conn.execute(
                    "SELECT vector_id,chunk_id FROM items WHERE collection=? AND document_id=? AND generation=? AND index_version=?",
                    (name, *replace),
                ).fetchall()
                for row in existing:
                    if row["chunk_id"] not in retained:
                        conn.execute("DELETE FROM items WHERE vector_id=?", (row["vector_id"],))
            conn.execute(
                "UPDATE collections SET revision=revision+1 WHERE name=?", (name,)
            )

    def delete(
        self,
        name: str,
        *,
        document_id: str | None = None,
        chunk_ids: Sequence[str] | None = None,
        generation: str | None = None,
    ) -> None:
        clauses, params = ["collection=?"], [name]
        if document_id is not None:
            clauses.append("document_id=?")
            params.append(document_id)
        if generation is not None:
            clauses.append("generation=?")
            params.append(generation)
        with self.transaction() as conn:
            if chunk_ids is not None:
                for chunk_id in chunk_ids:
                    conn.execute(
                        "DELETE FROM items WHERE "
                        + " AND ".join(clauses)
                        + " AND chunk_id=?",
                        (*params, chunk_id),
                    )
            else:
                conn.execute("DELETE FROM items WHERE " + " AND ".join(clauses), params)
            conn.execute(
                "UPDATE collections SET revision=revision+1 WHERE name=?", (name,)
            )

    def rows(
        self,
        name: str,
        *,
        with_vectors: bool = False,
        with_coarse: bool = False,
        vector_ids: Sequence[int] | None = None,
        chunk_id: str | None = None,
        document_id: str | None = None,
        generation: str | None = None,
        index_version: str | None = None,
    ) -> list[VectorItem]:
        with self.lock:
            schema = self.collection(name)
            if schema is None:
                return []
            fields = "vector_id,chunk_id,document_id,payload,generation,index_version,token_count"
            fields += ",vector" if with_vectors else ""
            fields += ",coarse" if with_coarse else ""
            # Bound IN lists for SQLite builds with different variable limits.
            batches = (
                [None]
                if vector_ids is None
                else [vector_ids[i : i + 400] for i in range(0, len(vector_ids), 400)]
            )
            result = []
            for ids in batches:
                query, params = f"SELECT {fields} FROM items WHERE collection=?", [name]
                for field, value in (("chunk_id", chunk_id), ("document_id", document_id),
                                     ("generation", generation), ("index_version", index_version)):
                    if value is not None:
                        query += f" AND {field}=?"
                        params.append(value)
                if ids is not None:
                    query += " AND vector_id IN (" + ",".join("?" for _ in ids) + ")"
                    params.extend(ids)
                for row in self.connection.execute(
                    query + " ORDER BY vector_id", params
                ):
                    try:
                        chunk = DocumentChunk.model_validate_json(row["payload"])
                        if (chunk.chunk_id, chunk.document_id) != (
                            row["chunk_id"],
                            row["document_id"],
                        ):
                            raise ValueError(
                                "chunk identity disagrees with stored columns"
                            )
                        if (
                            generation_key(
                                chunk.metadata.get("index_generation"), allow_empty=True
                            )
                            != row["generation"]
                        ):
                            raise ValueError(
                                "chunk generation disagrees with stored generation"
                            )
                        vector = None
                        if with_vectors:
                            if row["token_count"] < 1 or (
                                schema["kind"] == "text" and row["token_count"] != 1
                            ):
                                raise ValueError("invalid token count")
                            shape = (
                                (row["token_count"], schema["dimension"])
                                if schema["kind"] == "visual"
                                else (schema["dimension"],)
                            )
                            vector = (
                                np.frombuffer(row["vector"], dtype="<f4")
                                .reshape(shape)
                                .copy()
                            )
                            if not np.isfinite(vector).all():
                                raise ValueError("non-finite stored vector")
                        coarse = None
                        if with_coarse and row["coarse"] is not None:
                            coarse = vector_array(
                                np.frombuffer(row["coarse"], dtype="<f4"),
                                schema["dimension"],
                            )
                        result.append(
                            VectorItem(
                                row["vector_id"],
                                chunk,
                                row["generation"],
                                row["index_version"],
                                row["token_count"],
                                vector,
                                coarse,
                            )
                        )
                    except (ValueError, TypeError) as exc:
                        raise RagVectorStoreError(
                            "invalid persisted vector item"
                        ) from exc
            return result

    def backup(self, destination: str | Path) -> None:
        with self.lock, sqlite3.connect(str(destination)) as target:
            self.connection.backup(target)

    def count(self, name: str, *, document_ids: Sequence[str] | None = None, generation: str | None = None) -> int:
        with self.lock:
            documents = sorted(set(document_ids)) if document_ids is not None else None
            batches = [None] if documents is None else [documents[i:i+400] for i in range(0,len(documents),400)]
            total = 0
            for batch in batches:
                query, params = "SELECT COUNT(*) FROM items WHERE collection=?", [name]
                if generation is not None:
                    query += " AND generation=?"
                    params.append(generation)
                if batch is not None:
                    query += " AND document_id IN (" + ",".join("?" for _ in batch) + ")"
                    params.extend(batch)
                total += self.connection.execute(query, params).fetchone()[0]
            return total

    def close(self) -> None:
        with self.lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            if self._owner is not None:
                # Closing the OS handle releases the lock, including after crashes.
                self._owner.close()
                self._owner = None
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
