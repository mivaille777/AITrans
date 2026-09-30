from __future__ import annotations

import json
import sqlite3

import pytest

from backend.rag.graph.models import (
    GraphEntity,
    GraphGeneration,
    GraphRelation,
    RelationSource,
)
from backend.rag.graph.repository import GraphRepository


def test_corrupted_payload_cannot_escape_scoped_identity(tmp_path, graph_chunk):
    repository = GraphRepository(tmp_path / "graph.sqlite3")
    _, chunk = graph_chunk()
    _, relation = write_graph(repository, chunk)
    payload = relation.model_dump(mode="json")
    payload["document_id"] = "forbidden"
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE relation SET payload=?", (json.dumps(payload),))
    with pytest.raises(ValueError, match="identity disagrees"):
        repository.list_relations(
            scope_id="workspace",
            allowed_document_ids=("paper",),
            active_generations={"paper": "ready"},
        )


def write_graph(
    repository, chunk, *, scope="workspace", generation="ready", suffix="", alias=None
):
    entities = [
        GraphEntity(
            entity_id=name + suffix,
            scope_id=scope,
            canonical_name=name,
            entity_type="model",
            aliases=[alias or name.upper()],
        )
        for name in ("Alpha", "Beta")
    ]
    relation = GraphRelation(
        relation_id="relation" + suffix,
        scope_id=scope,
        document_id=chunk.document_id,
        generation_id=generation,
        source_entity_id=entities[0].entity_id,
        target_entity_id=entities[1].entity_id,
        predicate="uses",
        confidence=0.9,
        extractor_version="fixture-v1",
        sources=[
            RelationSource(chunk_id=chunk.chunk_id, source_span=chunk.source_span)
        ],
    )
    record = GraphGeneration(
        scope_id=scope,
        document_id=chunk.document_id,
        generation_id=generation,
        index_version="fixture-v1",
        chunk_ids=[chunk.chunk_id],
    )
    repository.write_generation(
        record,
        entities=entities,
        relations=[relation],
        chunk_entities={chunk.chunk_id: [e.entity_id for e in entities]},
        chunks=[chunk],
    )
    return record, relation


def test_schema_persistence_scoped_reads_and_delete(tmp_path, graph_chunk):
    path = tmp_path / "graph.sqlite3"
    repository = GraphRepository(path)
    _, chunk = graph_chunk()
    record, relation = write_graph(repository, chunk)
    write_graph(repository, chunk, scope="other", suffix="-other")
    repository = GraphRepository(path)
    kwargs = {
        "scope_id": "workspace",
        "allowed_document_ids": ("paper",),
        "active_generations": {"paper": "ready"},
    }

    assert repository.get_generation("workspace", "paper", "ready") == record
    assert repository.list_relations(**kwargs) == [relation]
    assert [e.entity_id for e in repository.find_entities("ＡＬＰＨＡ", **kwargs)] == [
        "Alpha"
    ]
    assert repository.list_relations(**{**kwargs, "allowed_document_ids": ()}) == []
    assert (
        repository.list_relations(**{**kwargs, "active_generations": {"paper": "old"}})
        == []
    )
    assert (
        repository.list_relations(**{**kwargs, "allowed_document_ids": ("forbidden",)})
        == []
    )
    repository.delete_document("workspace", "paper")
    assert repository.list_generations("workspace") == []
    assert repository.find_entities("Alpha", **kwargs) == []
    assert len(repository.list_generations("other")) == 1
    with sqlite3.connect(path) as connection:
        tables = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "entity",
            "alias",
            "relation",
            "relation_span",
            "chunk_entity",
            "graph_generation",
        } <= tables


def test_failed_write_rolls_back_all_graph_tables(tmp_path, graph_chunk):
    class FailingRepository(GraphRepository):
        def _validate_generation(self, connection, record):
            super()._validate_generation(connection, record)
            raise RuntimeError("injected before graph commit")

    path = tmp_path / "graph.sqlite3"
    repository = FailingRepository(path)
    _, chunk = graph_chunk()
    with pytest.raises(RuntimeError, match="injected"):
        write_graph(repository, chunk)
    assert repository.list_generations("workspace") == []
    with sqlite3.connect(path) as connection:
        for table in ("entity", "alias", "relation", "relation_span", "chunk_entity"):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )


def test_retained_versions_only_expose_requested_active_generation(
    tmp_path, graph_chunk
):
    repository = GraphRepository(tmp_path / "graph.sqlite3")
    _, chunk = graph_chunk()
    write_graph(repository, chunk, generation="old")
    write_graph(repository, chunk, generation="next", suffix="-next")
    kwargs = {
        "scope_id": "workspace",
        "allowed_document_ids": ("paper",),
        "active_generations": {"paper": "next"},
    }
    assert [r.generation_id for r in repository.list_relations(**kwargs)] == ["next"]
    repository.delete_generation("workspace", "paper", "next")
    assert repository.list_relations(**kwargs) == []
    assert [
        r.generation_id
        for r in repository.list_relations(
            **{**kwargs, "active_generations": {"paper": "old"}}
        )
    ] == ["old"]


def test_unverified_span_and_cross_scope_endpoints_are_rejected(tmp_path, graph_chunk):
    repository = GraphRepository(tmp_path / "graph.sqlite3")
    _, chunk = graph_chunk()
    corrupt = chunk.model_copy(update={"text": "invented text"})
    with pytest.raises(ValueError, match="source"):
        write_graph(repository, corrupt)
    assert repository.list_generations("workspace") == []
    record, relation = write_graph(repository, chunk)
    repository.delete_generation("workspace", "paper", "ready")
    wrong_entity = GraphEntity(
        entity_id="Alpha", scope_id="other", canonical_name="Alpha", entity_type="model"
    )
    with pytest.raises(ValueError, match="scope"):
        repository.write_generation(
            record,
            entities=[wrong_entity],
            relations=[relation],
            chunk_entities={},
            chunks=[chunk],
        )


def test_unknown_scope_or_generation_is_not_global_retrieval(tmp_path):
    repository = GraphRepository(tmp_path / "graph.sqlite3")
    with pytest.raises(ValueError, match="scope"):
        repository.list_relations(
            scope_id="", allowed_document_ids=(), active_generations={}
        )
    with pytest.raises(ValueError, match="resolved"):
        repository.list_relations(
            scope_id="workspace", allowed_document_ids=None, active_generations={}
        )


def test_shared_entity_does_not_leak_private_document_alias(tmp_path, graph_chunk):
    repository = GraphRepository(tmp_path / "graph.sqlite3")
    _, public = graph_chunk(document_id="public")
    _, private = graph_chunk(document_id="private")
    write_graph(repository, public)
    write_graph(repository, private, alias="secret-name")
    kwargs = {
        "scope_id": "workspace",
        "allowed_document_ids": ("public",),
        "active_generations": {"public": "ready", "private": "ready"},
    }

    assert repository.find_entities("secret-name", **kwargs) == []
    assert "secret-name" not in repository.find_entities("Alpha", **kwargs)[0].aliases


def test_large_allowlist_does_not_exceed_sql_expression_limit(tmp_path, graph_chunk):
    repository = GraphRepository(tmp_path / "graph.sqlite3")
    _, chunk = graph_chunk()
    write_graph(repository, chunk)
    generations = {f"document-{i}": "ready" for i in range(1200)}
    generations["paper"] = "ready"
    assert (
        len(
            repository.list_relations(
                scope_id="workspace",
                allowed_document_ids=tuple(generations),
                active_generations=generations,
            )
        )
        == 1
    )
