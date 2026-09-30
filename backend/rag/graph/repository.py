from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from hashlib import sha256
from pathlib import Path

from backend.rag.graph.models import (
    GRAPH_SCHEMA_VERSION,
    GraphEntity,
    GraphGeneration,
    GraphRelation,
    normalize_alias,
)
from backend.rag.models import DocumentChunk


class GraphRepository:
    """Versioned graph storage; the caller's manifest remains the publish pointer."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] not in {
                0,
                GRAPH_SCHEMA_VERSION,
            }:
                raise ValueError("unsupported graph schema version")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS graph_generation (
                    scope_id TEXT NOT NULL, document_id TEXT NOT NULL,
                    generation_id TEXT NOT NULL, index_version TEXT NOT NULL,
                    chunk_ids TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('building','ready')),
                    PRIMARY KEY(scope_id, document_id, generation_id)
                );
                CREATE TABLE IF NOT EXISTS entity (
                    scope_id TEXT NOT NULL, entity_id TEXT NOT NULL,
                    canonical_name TEXT NOT NULL, entity_type TEXT NOT NULL, description TEXT NOT NULL,
                    PRIMARY KEY(scope_id, entity_id)
                );
                CREATE TABLE IF NOT EXISTS alias (
                    scope_id TEXT NOT NULL, document_id TEXT NOT NULL, generation_id TEXT NOT NULL, entity_id TEXT NOT NULL,
                    name TEXT NOT NULL, normalized_name TEXT NOT NULL,
                    PRIMARY KEY(scope_id, document_id, generation_id, entity_id, normalized_name),
                    FOREIGN KEY(scope_id, document_id, generation_id) REFERENCES graph_generation ON DELETE CASCADE,
                    FOREIGN KEY(scope_id, entity_id) REFERENCES entity ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS chunk_entity (
                    scope_id TEXT NOT NULL, document_id TEXT NOT NULL, generation_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL, entity_id TEXT NOT NULL,
                    PRIMARY KEY(scope_id, document_id, generation_id, chunk_id, entity_id),
                    FOREIGN KEY(scope_id, document_id, generation_id) REFERENCES graph_generation ON DELETE CASCADE,
                    FOREIGN KEY(scope_id, entity_id) REFERENCES entity ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS relation (
                    scope_id TEXT NOT NULL, document_id TEXT NOT NULL, generation_id TEXT NOT NULL,
                    relation_id TEXT NOT NULL, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(scope_id, document_id, generation_id, relation_id),
                    FOREIGN KEY(scope_id, document_id, generation_id) REFERENCES graph_generation ON DELETE CASCADE,
                    FOREIGN KEY(scope_id, source_entity_id) REFERENCES entity,
                    FOREIGN KEY(scope_id, target_entity_id) REFERENCES entity
                );
                CREATE TABLE IF NOT EXISTS relation_span (
                    scope_id TEXT NOT NULL, document_id TEXT NOT NULL, generation_id TEXT NOT NULL,
                    relation_id TEXT NOT NULL, chunk_id TEXT NOT NULL, source_span TEXT NOT NULL,
                    PRIMARY KEY(scope_id, document_id, generation_id, relation_id, chunk_id, source_span),
                    FOREIGN KEY(scope_id, document_id, generation_id, relation_id) REFERENCES relation ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS alias_lookup ON alias(scope_id, normalized_name);
                CREATE INDEX IF NOT EXISTS chunk_entity_lookup ON chunk_entity(scope_id, entity_id, document_id, generation_id);
                CREATE INDEX IF NOT EXISTS relation_source ON relation(scope_id, source_entity_id, document_id, generation_id);
                CREATE INDEX IF NOT EXISTS relation_target ON relation(scope_id, target_entity_id, document_id, generation_id);
                CREATE INDEX IF NOT EXISTS span_chunk ON relation_span(scope_id, document_id, generation_id, chunk_id);
            """)
            connection.execute(f"PRAGMA user_version = {GRAPH_SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def write_generation(
        self,
        record: GraphGeneration,
        *,
        entities: list[GraphEntity],
        relations: list[GraphRelation],
        chunk_entities: dict[str, list[str]],
        chunks: list[DocumentChunk],
    ) -> None:
        identity = (record.scope_id, record.document_id, record.generation_id)
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
        if (
            len(chunk_map) != len(chunks)
            or len(record.chunk_ids) != len(chunks)
            or set(chunk_map) != set(record.chunk_ids)
        ):
            raise ValueError("graph generation chunk IDs do not match source chunks")
        if any(chunk.document_id != record.document_id for chunk in chunks):
            raise ValueError("graph source chunks belong to another document")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO graph_generation VALUES (?,?,?,?,?,?)",
                (
                    *identity,
                    record.index_version,
                    json.dumps(record.chunk_ids),
                    "building",
                ),
            )
            for entity in entities:
                if entity.scope_id != record.scope_id:
                    raise ValueError("graph entity scope disagrees with generation")
                stored = connection.execute(
                    "SELECT * FROM entity WHERE scope_id=? AND entity_id=?",
                    (entity.scope_id, entity.entity_id),
                ).fetchone()
                if stored is not None and any(
                    normalize_alias(stored[key])
                    != normalize_alias(getattr(entity, key))
                    for key in ("canonical_name", "entity_type", "description")
                ):
                    raise ValueError("graph entity identity collision")
                connection.execute(
                    "INSERT OR IGNORE INTO entity VALUES (?,?,?,?,?)",
                    (
                        entity.scope_id,
                        entity.entity_id,
                        entity.canonical_name,
                        entity.entity_type,
                        entity.description,
                    ),
                )
                for alias in (entity.canonical_name, *entity.aliases):
                    normalized = normalize_alias(alias)
                    if normalized:
                        connection.execute(
                            "INSERT OR IGNORE INTO alias VALUES (?,?,?,?,?,?)",
                            (*identity, entity.entity_id, alias, normalized),
                        )
            for chunk_id, entity_ids in chunk_entities.items():
                if chunk_id not in chunk_map:
                    raise ValueError("graph entity refers to a missing source chunk")
                for entity_id in set(entity_ids):
                    connection.execute(
                        "INSERT INTO chunk_entity VALUES (?,?,?,?,?)",
                        (*identity, chunk_id, entity_id),
                    )
            for relation in relations:
                if (
                    relation.scope_id,
                    relation.document_id,
                    relation.generation_id,
                ) != identity:
                    raise ValueError(
                        "graph relation scope/generation disagrees with source"
                    )
                for source in relation.sources:
                    chunk = chunk_map.get(source.chunk_id)
                    if chunk is None or chunk.source_span is None:
                        raise ValueError("graph relation has no source chunk span")
                    span = source.source_span
                    anchor = chunk.source_span
                    start, end = (
                        span.start_char - chunk.start_char,
                        span.end_char - chunk.start_char,
                    )
                    if (
                        span.document_hash != anchor.document_hash
                        or span.document_text_hash != anchor.document_text_hash
                        or span.source_uri != anchor.source_uri
                        or start < 0
                        or end > len(chunk.text)
                        or sha256(chunk.text.encode()).hexdigest() != anchor.quote_hash
                        or sha256(chunk.text[start:end].encode()).hexdigest()
                        != span.quote_hash
                    ):
                        raise ValueError(
                            "graph relation source span does not resolve to source text"
                        )
                    if not {
                        relation.source_entity_id,
                        relation.target_entity_id,
                    }.issubset(chunk_entities.get(source.chunk_id, [])):
                        raise ValueError(
                            "graph relation endpoints have no source chunk mapping"
                        )
                connection.execute(
                    "INSERT INTO relation VALUES (?,?,?,?,?,?,?)",
                    (
                        *identity,
                        relation.relation_id,
                        relation.source_entity_id,
                        relation.target_entity_id,
                        relation.model_dump_json(),
                    ),
                )
                for source in relation.sources:
                    connection.execute(
                        "INSERT INTO relation_span VALUES (?,?,?,?,?,?)",
                        (
                            *identity,
                            relation.relation_id,
                            source.chunk_id,
                            source.source_span.model_dump_json(),
                        ),
                    )
            self._validate_generation(connection, record)
            connection.execute(
                "UPDATE graph_generation SET status='ready' WHERE scope_id=? AND document_id=? AND generation_id=?",
                identity,
            )

    def _validate_generation(
        self, connection: sqlite3.Connection, record: GraphGeneration
    ) -> None:
        missing = connection.execute(
            """SELECT COUNT(*) FROM relation r
            WHERE r.scope_id=? AND r.document_id=? AND r.generation_id=?
            AND NOT EXISTS (SELECT 1 FROM relation_span s WHERE
                s.scope_id=r.scope_id AND s.document_id=r.document_id AND s.generation_id=r.generation_id AND s.relation_id=r.relation_id)
        """,
            (record.scope_id, record.document_id, record.generation_id),
        ).fetchone()[0]
        if missing:
            raise ValueError("graph generation contains relations without source spans")

    @staticmethod
    def _generation(row: sqlite3.Row) -> GraphGeneration:
        return GraphGeneration(
            **{**dict(row), "chunk_ids": json.loads(row["chunk_ids"])}
        )

    def get_generation(
        self, scope_id: str, document_id: str, generation_id: str
    ) -> GraphGeneration | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM graph_generation WHERE scope_id=? AND document_id=? AND generation_id=?",
                (scope_id, document_id, generation_id),
            ).fetchone()
            return self._generation(row) if row else None

    def list_generations(self, scope_id: str) -> list[GraphGeneration]:
        with closing(self._connect()) as connection:
            return [
                self._generation(row)
                for row in connection.execute(
                    "SELECT * FROM graph_generation WHERE scope_id=? ORDER BY document_id, generation_id",
                    (scope_id,),
                )
            ]

    @staticmethod
    def _scope_filter(
        scope_id: str,
        allowed_document_ids: tuple[str, ...],
        active_generations: Mapping[str, str | None],
    ) -> tuple[str, list[str]]:
        if not scope_id.strip():
            raise ValueError("graph scope must be explicit")
        if allowed_document_ids is None or active_generations is None:
            raise ValueError("graph access scope and generations must be resolved")
        pairs = {
            doc: active_generations[doc]
            for doc in sorted(set(allowed_document_ids))
            if active_generations.get(doc)
        }
        if not pairs:
            return "0", []
        clause = (
            "g.scope_id=? AND g.status='ready' AND EXISTS ("
            "SELECT 1 FROM json_each(?) allowed WHERE allowed.key=g.document_id "
            "AND allowed.value=g.generation_id)"
        )
        return clause, [scope_id, json.dumps(pairs)]

    def list_relations(
        self,
        *,
        scope_id: str,
        allowed_document_ids: tuple[str, ...],
        active_generations: Mapping[str, str | None],
    ) -> list[GraphRelation]:
        clause, params = self._scope_filter(
            scope_id, allowed_document_ids, active_generations
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT r.* FROM relation r JOIN graph_generation g
                USING(scope_id, document_id, generation_id) WHERE {clause} ORDER BY r.relation_id""",
                params,
            )
            relations = []
            for row in rows:
                relation = GraphRelation.model_validate_json(row["payload"])
                if any(
                    getattr(relation, key) != row[key]
                    for key in (
                        "scope_id",
                        "document_id",
                        "generation_id",
                        "relation_id",
                        "source_entity_id",
                        "target_entity_id",
                    )
                ):
                    raise ValueError(
                        "stored graph relation identity disagrees with scoped source"
                    )
                relations.append(relation)
            return relations

    def find_entities(
        self,
        name: str,
        *,
        scope_id: str,
        allowed_document_ids: tuple[str, ...],
        active_generations: Mapping[str, str | None],
        limit: int = 20,
    ) -> list[GraphEntity]:
        if limit <= 0:
            raise ValueError("graph entity limit must be positive")
        clause, params = self._scope_filter(
            scope_id, allowed_document_ids, active_generations
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT DISTINCT e.* FROM entity e JOIN alias a USING(scope_id, entity_id)
                JOIN chunk_entity c ON (c.scope_id=a.scope_id AND c.document_id=a.document_id AND c.generation_id=a.generation_id AND c.entity_id=a.entity_id)
                JOIN graph_generation g
                ON (g.scope_id=a.scope_id AND g.document_id=a.document_id AND g.generation_id=a.generation_id)
                WHERE {clause} AND a.normalized_name=? ORDER BY e.entity_id LIMIT ?""",
                [*params, normalize_alias(name), limit],
            ).fetchall()
            return [
                GraphEntity(
                    **dict(row),
                    aliases=[
                        alias[0]
                        for alias in connection.execute(
                            f"SELECT DISTINCT a.name FROM alias a JOIN graph_generation g USING(scope_id, document_id, generation_id) WHERE {clause} AND a.entity_id=? ORDER BY a.name",
                            [*params, row["entity_id"]],
                        )
                    ],
                )
                for row in rows
            ]

    def delete_generation(
        self, scope_id: str, document_id: str, generation_id: str
    ) -> None:
        self._delete(scope_id, document_id, generation_id)

    def delete_document(self, scope_id: str, document_id: str) -> None:
        self._delete(scope_id, document_id, None)

    def _delete(
        self, scope_id: str, document_id: str, generation_id: str | None
    ) -> None:
        with closing(self._connect()) as connection, connection:
            clause, params = "scope_id=? AND document_id=?", [scope_id, document_id]
            if generation_id is not None:
                clause += " AND generation_id=?"
                params.append(generation_id)
            connection.execute(f"DELETE FROM graph_generation WHERE {clause}", params)
            connection.execute(
                """DELETE FROM entity WHERE scope_id=? AND NOT EXISTS
                (SELECT 1 FROM chunk_entity c WHERE c.scope_id=entity.scope_id AND c.entity_id=entity.entity_id)""",
                (scope_id,),
            )
