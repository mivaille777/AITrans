from __future__ import annotations

from hashlib import sha256

import pytest

from backend.rag.chunking import StructureAwareChunker
from backend.rag.models import KnowledgeDocument, NormalizedDocument


@pytest.fixture
def graph_document():
    def make(text="Alpha uses Beta.", document_id="paper"):
        return NormalizedDocument(
            document=KnowledgeDocument(
                document_id=document_id,
                source_uri=f"file:///{document_id}.txt",
                content_hash=sha256(text.encode()).hexdigest(),
            ),
            text=text,
            metadata={"parser_version": "fixture-v1"},
        )

    return make


@pytest.fixture
def graph_chunk(graph_document):
    def make(text="Alpha uses Beta.", document_id="paper"):
        document = graph_document(text, document_id)
        return document, StructureAwareChunker().chunk(document)[0]

    return make


@pytest.fixture
def retrieval_graph(tmp_path, graph_chunk):
    from backend.rag.graph.models import (
        GraphEntity,
        GraphGeneration,
        GraphRelation,
        RelationSource,
    )
    from backend.rag.graph.repository import GraphRepository

    repository = GraphRepository(tmp_path / "retrieval.sqlite3")
    chunks, active = {}, {}

    def add(subject, target, *, scope="knowledge", generation="g1", document_id=None):
        doc = document_id or f"paper-{subject}-{target}"
        _, chunk = graph_chunk(f"{subject} uses {target}.", doc)
        chunk = chunk.model_copy(update={"metadata": {"index_generation": generation}})
        chunks[chunk.chunk_id, generation] = chunk
        active[doc] = generation
        entities = [
            GraphEntity(
                entity_id=name, scope_id=scope, canonical_name=name, entity_type="model"
            )
            for name in (subject, target)
        ]
        relation = GraphRelation(
            relation_id=f"{subject}-{target}",
            scope_id=scope,
            document_id=doc,
            generation_id=generation,
            source_entity_id=subject,
            target_entity_id=target,
            predicate="uses",
            confidence=0.9,
            extractor_version="labelled-v1",
            sources=[
                RelationSource(chunk_id=chunk.chunk_id, source_span=chunk.source_span)
            ],
        )
        repository.write_generation(
            GraphGeneration(
                scope_id=scope,
                document_id=doc,
                generation_id=generation,
                index_version="labelled-v1",
                chunk_ids=[chunk.chunk_id],
            ),
            entities=entities,
            relations=[relation],
            chunk_entities={chunk.chunk_id: [subject, target]},
            chunks=[chunk],
        )
        return chunk

    class Store:
        def get_chunk(self, chunk_id, *, generation_id=None):
            return chunks.get((chunk_id, generation_id))

    return repository, Store(), active, add, chunks
