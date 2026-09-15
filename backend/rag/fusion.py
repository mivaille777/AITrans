from __future__ import annotations

from backend.rag.models import RetrievalCandidate


def rrf_fuse(
    ranked_lists: list[list[RetrievalCandidate]],
    *,
    limit: int,
    k: int = 60,
) -> list[RetrievalCandidate]:
    if limit <= 0 or k <= 0:
        raise ValueError("RRF limit and k must be positive")
    merged: dict[str, RetrievalCandidate] = {}
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for position, candidate in enumerate(ranked, start=1):
            chunk_id = candidate.chunk.chunk_id
            rank = candidate.rank or position
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            existing = merged.get(chunk_id)
            if existing is None:
                merged[chunk_id] = candidate.model_copy(deep=True)
            else:
                updates = {
                    "dense_score": existing.dense_score
                    if existing.dense_score is not None
                    else candidate.dense_score,
                    "sparse_score": existing.sparse_score
                    if existing.sparse_score is not None
                    else candidate.sparse_score,
                    "context_window": existing.context_window
                    if existing.context_window is not None
                    else candidate.context_window,
                }
                merged[chunk_id] = existing.model_copy(update=updates)

    ordered_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[
        :limit
    ]
    return [
        merged[chunk_id].model_copy(
            update={"fusion_score": scores[chunk_id], "rank": rank}
        )
        for rank, chunk_id in enumerate(ordered_ids, start=1)
    ]


__all__ = ["rrf_fuse"]
