from backend.rag.config import RagGraphConfig
from backend.rag.graph.query_entities import query_entities
from backend.rag.graph_retriever import GraphRetriever
from backend.rag.retrievers.base import RetrievalRequest


def request(active, query="Alpha", **kwargs):
    return RetrievalRequest(query=query, top_k=8, active_generations=active, **kwargs)


def retriever(repository, store, **kwargs):
    return GraphRetriever(
        repository=repository,
        store=store,
        config=RagGraphConfig(enabled=True, **kwargs),
    )


def test_alias_seed_returns_existing_original_chunk(retrieval_graph):
    repository, store, active, add, _ = retrieval_graph
    original = add("Alpha", "Beta")
    result = retriever(repository, store).retrieve_with_trace(
        request(active, "How does Ａｌｐｈａ work?")
    )
    assert result.candidates[0].chunk == original
    assert result.candidates[0].channel_hits[0].channel == "graph"
    assert result.metadata["seed_ids"] == ["Alpha"]
    assert result.candidates[0].trace_id
    assert result.candidates[0].graph_paths


def test_seed_scope_generation_type_and_empty_mapping_fail_closed(retrieval_graph):
    repository, store, active, add, chunks = retrieval_graph
    original = add("Alpha", "Beta")
    add("Secret", "Alpha", scope="private")
    adapter = retriever(repository, store)
    assert adapter.retrieve(request(active, "Unknown")) == []
    assert adapter.retrieve(request(active, allowed_document_ids=())) == []
    assert adapter.retrieve(request({original.document_id: "stale"})) == []
    assert adapter.retrieve(RetrievalRequest(query="Alpha", top_k=8)) == []
    assert (
        retriever(repository, store, entity_types=["dataset"]).retrieve(request(active))
        == []
    )
    chunks.clear()
    assert (
        adapter.retrieve_with_trace(request(active)).metadata["reason"]
        == "no_grounded_passage"
    )


def test_query_entity_phrases_and_work_budget():
    assert "gaussian process" in query_entities("What uses Gaussian process (GP)?")
    assert "gp" in query_entities("What uses Gaussian process (GP)?")
    assert "模型甲" in query_entities("模型甲使用什么")
    assert len(query_entities("word " * 3000, max_terms=4)) <= 4


def test_ambiguous_alias_is_not_selected_and_allowlist_resolves_it(
    retrieval_graph, graph_chunk
):
    from backend.rag.graph.models import GraphEntity, GraphGeneration

    repository, store, active, add, chunks = retrieval_graph
    original = add("Alpha", "Beta")
    _, other = graph_chunk("Alpha uses Beta. Alpha denotes another model.", "another-paper")
    other = other.model_copy(update={"metadata": {"index_generation": "g1"}})
    chunks[other.chunk_id, "g1"] = other
    active[other.document_id] = "g1"
    repository.write_generation(
        GraphGeneration(
            scope_id="knowledge",
            document_id=other.document_id,
            generation_id="g1",
            index_version="labelled-v1",
            chunk_ids=[other.chunk_id],
        ),
        entities=[
            GraphEntity(
                entity_id="different-alpha",
                scope_id="knowledge",
                canonical_name="Alpha",
                entity_type="model",
            )
        ],
        relations=[],
        chunk_entities={other.chunk_id: ["different-alpha"]},
        chunks=[other],
    )
    adapter = retriever(repository, store)
    assert adapter.retrieve_with_trace(request(active)).metadata["reason"] == "no_seed"
    scoped = adapter.retrieve(
        request(active, allowed_document_ids=(original.document_id,))
    )
    assert [hit.chunk.chunk_id for hit in scoped] == [original.chunk_id]
