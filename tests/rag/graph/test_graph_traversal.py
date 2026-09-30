from hashlib import sha256

import pytest

from backend.rag.graph.scoring import path_score
from backend.rag.source_span import resolve_source_span
from tests.rag.graph.test_graph_seeds import request, retriever


def test_two_hop_paths_recover_each_original_edge_and_one_hop_stops(retrieval_graph):
    repository, store, active, add, _ = retrieval_graph
    first = add("Alpha", "Beta")
    second = add("Beta", "Gamma")
    third = add("Gamma", "Delta")
    one = retriever(repository, store, max_hops=1).retrieve(request(active))
    two = retriever(repository, store, max_hops=2).retrieve(request(active))
    assert {candidate.chunk.chunk_id for candidate in one} == {first.chunk_id}
    assert {candidate.chunk.chunk_id for candidate in two} == {
        first.chunk_id,
        second.chunk_id,
    }
    assert third.chunk_id not in {candidate.chunk.chunk_id for candidate in two}
    reached = next(
        candidate for candidate in two if candidate.chunk.chunk_id == second.chunk_id
    )
    paths = [path for path in reached.graph_paths if path.edge_ids]
    assert [path.edge_ids for path in paths] == [
        ["Alpha-Beta"],
        ["Alpha-Beta", "Beta-Gamma"],
    ]
    originals = {chunk.source_uri: chunk.text for chunk in (first, second)}
    for path in paths:
        assert resolve_source_span(
            path.source_span, originals[path.source_span.source_uri]
        )
    assert reached.channel_hits[0].raw_score == pytest.approx(0.405)


def test_cycles_private_bridges_and_disallowed_documents_do_not_expand(retrieval_graph):
    repository, store, active, add, _ = retrieval_graph
    first = add("Alpha", "Beta")
    add("Beta", "Gamma")
    add("Gamma", "Alpha")
    add("Beta", "Secret", scope="private")
    adapter = retriever(repository, store)
    result = adapter.retrieve_with_trace(request(active))
    assert all(
        "Secret" not in path.node_ids
        for hit in result.candidates
        for path in hit.graph_paths
    )
    assert all(
        len(path.node_ids) == len(set(path.node_ids))
        for hit in result.candidates
        for path in hit.graph_paths
    )
    restricted = adapter.retrieve(
        request(active, allowed_document_ids=(first.document_id,))
    )
    assert {hit.chunk.document_id for hit in restricted} == {first.document_id}


def test_hot_node_obeys_work_and_output_budgets(retrieval_graph):
    repository, store, active, add, _ = retrieval_graph
    for i in range(30):
        add("Alpha", f"Neighbor{i}")
    result = retriever(
        repository, store, max_nodes=3, max_paths=4, max_edges=5
    ).retrieve_with_trace(request(active))
    assert result.metadata["visited_nodes"] <= 3
    assert result.metadata["path_count"] <= 4
    assert result.metadata["examined_edges"] <= 5
    assert result.metadata["truncated"]
    assert len(result.candidates) <= 4


def test_metadata_filter_cannot_be_used_as_a_hidden_bridge(retrieval_graph):
    from backend.rag.stores.base import VectorSearchFilter

    repository, store, active, add, chunks = retrieval_graph
    first = add("Alpha", "Beta")
    second = add("Beta", "Gamma")
    chunks[second.chunk_id, "g1"] = second.model_copy(
        update={"metadata": {"index_generation": "g1", "topic": "allowed"}}
    )
    result = retriever(repository, store).retrieve_with_trace(
        request(active, filters=VectorSearchFilter(metadata={"topic": "allowed"}))
    )
    assert first.chunk_id not in {hit.chunk.chunk_id for hit in result.candidates}
    assert result.candidates == []
    assert result.metadata["visited_nodes"] == 1


@pytest.mark.parametrize(
    "corruption", ["generation", "scope", "text", "span", "references"]
)
def test_invalid_or_filtered_source_is_not_a_citation(retrieval_graph, corruption):
    repository, store, active, add, chunks = retrieval_graph
    original = add("Alpha", "Beta")
    updates = {
        "generation": {"metadata": {"index_generation": "old"}},
        "scope": {"document_id": "forbidden"},
        "text": {"text": "fabricated source"},
        "span": {
            "source_span": original.source_span.model_copy(
                update={"quote_hash": sha256(b"wrong").hexdigest()}
            )
        },
        "references": {
            "metadata": {"index_generation": "g1", "section_kind": "references"}
        },
    }
    chunks[original.chunk_id, "g1"] = original.model_copy(update=updates[corruption])
    result = retriever(repository, store).retrieve_with_trace(request(active))
    assert result.candidates == []
    assert result.metadata["rejected_sources"] > 0


def test_deadline_discards_partial_results_and_stops_further_source_reads(
    retrieval_graph, monkeypatch
):
    import backend.rag.graph_retriever as module

    repository, store, active, add, _ = retrieval_graph
    add("Alpha", "Beta")
    now = [module.perf_counter()]
    monkeypatch.setattr(module, "perf_counter", lambda: now[0])
    original = store.get_chunk
    calls = []

    def slow(*args, **kwargs):
        calls.append(args)
        now[0] += 2
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "get_chunk", slow)
    result = retriever(repository, store, deadline_ms=1000).retrieve_with_trace(
        request(active)
    )
    assert result.candidates == []
    assert result.metadata["reason"] == "deadline_exceeded"
    assert len(calls) == 1


def test_path_scoring_rejects_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        path_score((1.1,))
