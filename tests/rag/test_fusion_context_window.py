from __future__ import annotations

from backend.rag.fusion import rrf_fuse
from backend.rag.models import (
    DocumentChunk,
    RetrievalCandidate,
    RetrievalContextWindow,
)


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
