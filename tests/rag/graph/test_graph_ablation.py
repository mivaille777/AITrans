import networkx as nx

from backend.rag.fusion import rrf_fuse
from backend.rag.models import ChannelHit, RetrievalCandidate
from tests.rag.graph.test_graph_seeds import request, retriever


def test_fixed_graph_hop_ppr_and_fusion_preserve_original_evidence(retrieval_graph):
    repository, store, active, add, _ = retrieval_graph
    first = add("Alpha", "Beta")
    bridge = add("Beta", "Gamma")
    add("Gamma", "Delta")
    query = request(active)
    one = retriever(repository, store, max_hops=1).retrieve(query)
    two = retriever(repository, store, max_hops=2).retrieve(query)
    assert bridge.chunk_id not in {hit.chunk.chunk_id for hit in one}
    assert bridge.chunk_id in {hit.chunk.chunk_id for hit in two}
    labelled = repository.list_relations(
        scope_id="knowledge",
        allowed_document_ids=tuple(active),
        active_generations=active,
    )
    reference = nx.Graph()
    for edge in labelled:
        reference.add_edge(
            edge.source_entity_id, edge.target_entity_id, weight=edge.confidence
        )
    ppr = nx.pagerank(
        reference, personalization={node: float(node == "Alpha") for node in reference}
    )
    assert ppr["Beta"] > ppr["Gamma"] > ppr["Delta"]
    vector = [
        RetrievalCandidate(
            chunk=first,
            rank=1,
            index_generation="g1",
            channel_hits=[ChannelHit(channel="vector", raw_score=0.8, rank=1)],
        )
    ]
    bm25 = [
        RetrievalCandidate(
            chunk=bridge,
            rank=1,
            index_generation="g1",
            channel_hits=[ChannelHit(channel="bm25", raw_score=2.0, rank=1)],
        )
    ]
    for channels in ([two], [vector, two], [vector, bm25, two]):
        fused = rrf_fuse(channels, limit=8)
        reached = next(hit for hit in fused if hit.chunk.chunk_id == bridge.chunk_id)
        assert reached.chunk == bridge
        assert reached.graph_paths
        assert any(hit.channel == "graph" for hit in reached.channel_hits)
