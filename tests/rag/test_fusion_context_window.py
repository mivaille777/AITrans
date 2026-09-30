from __future__ import annotations

import pytest

from backend.rag.fusion import rrf_fuse
from backend.rag.models import (
    ChannelHit,
    DocumentChunk,
    GraphPath,
    RetrievalCandidate,
    RetrievalContextWindow,
)
from backend.rag.source_span import SourceSpan


def test_rrf_dedupe_preserves_any_available_context_window() -> None:
    chunk = DocumentChunk(
        chunk_id="anchor",
        document_id="paper",
        text="anchor",
        section_path=["3 Methodology"],
        chunk_index=1,
    )
    neighbor = DocumentChunk(
        chunk_id="neighbor",
        document_id="paper",
        text="neighbor",
        section_path=["3 Methodology"],
        chunk_index=2,
    )
    window = RetrievalContextWindow(
        anchor_chunk_id="anchor",
        chunks=[chunk, neighbor],
        text="anchor\n\nneighbor",
        token_count=2,
    )
    without_window = RetrievalCandidate(chunk=chunk, dense_score=0.9, rank=1)
    with_window = RetrievalCandidate(
        chunk=chunk,
        sparse_score=2.0,
        rank=1,
        context_window=window,
    )

    fused = rrf_fuse([[without_window], [with_window]], limit=1)

    assert fused[0].chunk.chunk_id == "anchor"
    assert fused[0].context_window == window
    assert fused[0].dense_score == 0.9
    assert fused[0].sparse_score == 2.0


def test_rrf_keeps_identical_chunk_ids_in_different_generations_separate() -> None:
    chunk = DocumentChunk(
        chunk_id="same", document_id="paper", text="evidence", chunk_index=0
    )
    candidates = [
        RetrievalCandidate(
            chunk=chunk.model_copy(
                update={"metadata": {"index_generation": generation}}
            ),
            dense_score=0.9,
            rank=1,
        )
        for generation in ("old", "ready")
    ]

    fused = rrf_fuse([[candidates[0]], [candidates[1]]], limit=2)

    assert len(fused) == 2
    assert {hit.index_generation for hit in fused} == {"old", "ready"}
    assert all(hit.fusion_score == pytest.approx(1 / 61) for hit in fused)


def test_rrf_preserves_original_channel_ranks_and_graph_sources() -> None:
    chunk = DocumentChunk(
        chunk_id="same", document_id="paper", text="evidence", chunk_index=0
    )
    path = GraphPath(
        node_ids=["entity"],
        source_span=SourceSpan.from_text(
            "evidence", start_char=0, end_char=8, document_hash="hash"
        ),
    )
    vector = RetrievalCandidate(
        chunk=chunk,
        dense_score=0.9,
        rank=3,
        index_generation="ready",
        channel_hits=[ChannelHit(channel="vector", raw_score=0.9, rank=3)],
        trace_id="trace",
    )
    graph = RetrievalCandidate(
        chunk=chunk,
        rank=7,
        index_generation="ready",
        graph_paths=[path],
        channel_hits=[ChannelHit(channel="graph", raw_score=0.2, rank=7)],
        trace_id="trace",
    )

    fused = rrf_fuse([[vector], [graph]], limit=1)[0]

    assert fused.rank == 1
    assert fused.channel_hits == vector.channel_hits + graph.channel_hits
    assert fused.graph_paths == [path]
    assert fused.index_generation == "ready"
    assert fused.trace_id == "trace"
    assert fused.fusion_score == pytest.approx(1 / 63 + 1 / 67)
    assert vector.graph_paths == []
