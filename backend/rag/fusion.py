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
    merged: dict[tuple[str, str], RetrievalCandidate] = {}
    scores: dict[tuple[str, str], float] = {}
    for ranked in ranked_lists:
        for position, candidate in enumerate(ranked, start=1):
            generation = (
                candidate.index_generation
                or candidate.chunk.metadata.get("index_generation")
                or ""
            )
            key = (generation, candidate.chunk.chunk_id)
            rank = candidate.rank or position
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate.model_copy(
                    deep=True, update={"index_generation": generation or None}
                )
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
                    "channel_hits": [*existing.channel_hits, *candidate.channel_hits],
                    "graph_paths": [*existing.graph_paths, *candidate.graph_paths],
                    "trace_id": existing.trace_id or candidate.trace_id,
                }
                merged[key] = existing.model_copy(update=updates)

    ordered_ids = sorted(scores, key=lambda key: (-scores[key], key[1], key[0]))[:limit]
    return [
        merged[key].model_copy(update={"fusion_score": scores[key], "rank": rank})
        for rank, key in enumerate(ordered_ids, start=1)
    ]


__all__ = ["rrf_fuse"]
