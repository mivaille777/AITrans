from backend.rag.fusion import rrf_fuse
from backend.rag.models import DocumentChunk, RetrievalCandidate


def candidate(chunk_id: str, rank: int, *, dense=False, sparse=False):
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id="doc",
            text=chunk_id,
            chunk_index=rank,
        ),
        dense_score=0.9 if dense else None,
        sparse_score=4.0 if sparse else None,
        rank=rank,
    )


def test_rrf_merges_overlap_and_preserves_source_scores() -> None:
    results = rrf_fuse(
        [
            [candidate("shared", 1, dense=True), candidate("dense", 2, dense=True)],
            [candidate("shared", 1, sparse=True), candidate("sparse", 2, sparse=True)],
        ],
        limit=3,
    )

    assert results[0].chunk.chunk_id == "shared"
    assert results[0].dense_score == 0.9
    assert results[0].sparse_score == 4.0
    assert results[0].fusion_score == 2 / 61


def test_rrf_ties_are_deterministic_and_limit_is_applied() -> None:
    results = rrf_fuse(
        [[candidate("b", 1, dense=True)], [candidate("a", 1, sparse=True)]],
        limit=1,
    )

    assert [item.chunk.chunk_id for item in results] == ["a"]
    assert results[0].rank == 1
