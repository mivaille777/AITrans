from __future__ import annotations

import re
import sqlite3

import pytest

from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
)
from backend.rag.benchmarks.runtime import build_benchmark_rag_runtime
from backend.rag.config import RagConfig
from backend.rag.graph.extractor import GraphExtractor
from backend.rag.graph.indexer import GraphIndexer
from backend.rag.graph.repository import GraphRepository
from backend.rag.index_manifest import IndexGenerationStatus, IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.source_span import resolve_source_span


class Embedding:
    model_name = "graph-fixture"
    dimension = 4

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0, 0.0]


class ControlledExtractor:
    version, prompt_id, provider_name, model = (
        "fixture-v1",
        "fixture:v1",
        "fixture",
        "recorded-output",
    )

    def extract(self, note):
        matches = list(re.finditer(r"(\w+) uses (\w+)\.", note.source_text))
        names = sorted({name for match in matches for name in match.groups()})
        return ResearchMemoryExtractionDraft(
            entities=tuple(ResearchMemoryEntityDraft(name, "model") for name in names),
            claims=tuple(
                ResearchMemoryClaimDraft(match[0], evidence_excerpt=match[0])
                for match in matches
            ),
            relations=tuple(
                ResearchMemoryRelationDraft(match[1], "uses", match[2], i, 0.9)
                for i, match in enumerate(matches)
            ),
        )


@pytest.fixture
def graph_runtime(tmp_path):
    runtime = build_benchmark_rag_runtime(
        tmp_path / "runtime",
        config=RagConfig(embedding={"dimension": 4}),
        embedding_provider=Embedding(),
    )
    graph = GraphIndexer(
        repository=GraphRepository(tmp_path / "graph.sqlite3"),
        extractor=GraphExtractor(ControlledExtractor()),
        scope_id="workspace",
    )
    service = IndexService(
        chunker=runtime.chunker,
        embedding_provider=runtime.embedding_provider,
        vector_store=runtime.vector_store,
        sparse_retriever=runtime.sparse_retriever,
        manifest=runtime.manifest,
        graph_indexer=graph,
    )
    yield service, graph, runtime
    runtime.close()


def active_relations(graph, manifest):
    active = manifest.list_active_generations()
    return graph.repository.list_relations(
        scope_id=graph.scope_id,
        allowed_document_ids=tuple(active),
        active_generations=active,
    )


def test_import_reimport_delete_and_reuse_existing_entry_point(tmp_path, graph_runtime):
    service, graph, runtime = graph_runtime
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("Alpha uses Beta.", encoding="utf-8")
    second.write_text("Beta uses Gamma.", encoding="utf-8")
    a, b = service.index_document(first), service.index_document(second)
    assert a.status is b.status is IndexStatus.READY
    relations = active_relations(graph, runtime.manifest)
    assert len(relations) == 2
    for relation in relations:
        span = relation.sources[0].source_span
        text = (
            first.read_text()
            if relation.document_id == a.document_id
            else second.read_text()
        )
        assert resolve_source_span(span, text) == text
    assert service.index_document(first).reused_existing is True
    old_generation = runtime.manifest.get(a.document_id).generation_id
    first.write_text("Delta uses Gamma.", encoding="utf-8")
    assert service.index_document(first).status is IndexStatus.READY
    assert all(
        r.generation_id != old_generation
        for r in active_relations(graph, runtime.manifest)
    )
    assert service.delete_document(a.document_id)
    assert len(active_relations(graph, runtime.manifest)) == 1
    assert service.delete_document(b.document_id)
    with sqlite3.connect(graph.repository.path) as connection:
        for table in (
            "graph_generation",
            "entity",
            "alias",
            "chunk_entity",
            "relation",
            "relation_span",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )


@pytest.mark.parametrize("failure", ["graph_write", "manifest_publish"])
def test_failed_new_graph_never_replaces_previous_active_version(
    tmp_path, graph_runtime, monkeypatch, failure
):
    service, graph, runtime = graph_runtime
    path = tmp_path / "paper.txt"
    path.write_text("Alpha uses Beta.")
    indexed = service.index_document(path)
    before = runtime.manifest.get(indexed.document_id)
    previous = active_relations(graph, runtime.manifest)
    path.write_text("Alpha uses Gamma.")
    if failure == "graph_write":
        original = graph.build_generation

        def fail(*args):
            original(*args)
            raise RuntimeError("injected graph failure after write")

        monkeypatch.setattr(graph, "build_generation", fail)
    else:

        def fail(*args, **kwargs):
            raise RuntimeError("injected manifest publish failure")

        monkeypatch.setattr(runtime.manifest, "publish_generation", fail)
    result = service.index_document(path)
    assert result.status is IndexStatus.FAILED
    assert "injected" in result.error
    assert runtime.manifest.get(indexed.document_id) == before
    assert active_relations(graph, runtime.manifest) == previous
    assert len(graph.repository.list_generations("workspace")) == 1


def test_missing_graph_forces_rebuild_instead_of_reusing_vectors_only(
    tmp_path, graph_runtime
):
    service, graph, runtime = graph_runtime
    path = tmp_path / "paper.txt"
    path.write_text("Alpha uses Beta.")
    indexed = service.index_document(path)
    old = runtime.manifest.get(indexed.document_id).generation_id
    graph.delete_generation(indexed.document_id, old)
    rebuilt = service.index_document(path)
    assert rebuilt.status is IndexStatus.READY
    assert not rebuilt.reused_existing
    assert runtime.manifest.get(indexed.document_id).generation_id != old
    assert len(active_relations(graph, runtime.manifest)) == 1


def test_restart_cleans_unpublished_graph_after_manifest_recovery(
    tmp_path, graph_runtime
):
    service, graph, runtime = graph_runtime
    path = tmp_path / "paper.txt"
    path.write_text("Alpha uses Beta.")
    indexed = service.index_document(path)
    from backend.rag.parsers import parse_document

    document = parse_document(path)
    document = document.model_copy(
        update={
            "document": document.document.model_copy(
                update={"document_id": indexed.document_id}
            )
        }
    )
    chunks = runtime.chunker.chunk(document)
    runtime.manifest.begin_generation(
        indexed.document_id, "interrupted", [c.chunk_id for c in chunks]
    )
    graph.build_generation(document, chunks, "interrupted")
    assert len(graph.repository.list_generations("workspace")) == 2
    assert len(active_relations(graph, runtime.manifest)) == 1
    runtime.manifest.recover_interrupted_operations()
    assert (
        runtime.manifest.get_generation(indexed.document_id, "interrupted").status
        is IndexGenerationStatus.FAILED
    )
    assert graph.recover(runtime.manifest) == [(indexed.document_id, "interrupted")]
    assert len(graph.repository.list_generations("workspace")) == 1


def test_graph_delete_failure_is_visible_and_keeps_other_stores(
    tmp_path, graph_runtime, monkeypatch
):
    service, graph, runtime = graph_runtime
    path = tmp_path / "paper.txt"
    path.write_text("Alpha uses Beta.")
    indexed = service.index_document(path)
    original = graph.delete_document

    def fail(document_id):
        raise RuntimeError("graph delete failed")

    monkeypatch.setattr(graph, "delete_document", fail)
    with pytest.raises(RuntimeError, match="graph delete failed"):
        service.delete_document(indexed.document_id)
    assert runtime.manifest.get(indexed.document_id).status is IndexStatus.READY
    assert runtime.vector_store.list_chunks()
    monkeypatch.setattr(graph, "delete_document", original)
    assert service.delete_document(indexed.document_id)
