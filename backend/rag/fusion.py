from __future__ import annotations

from backend.rag.models import RetrievalCandidate


def _candidate_key(candidate: RetrievalCandidate) -> tuple[str, str]:
    return (
        candidate.index_generation
        or candidate.chunk.metadata.get("index_generation")
        or "",
        candidate.chunk.chunk_id,
    )


def retain_list_coverage(
    fused: list[RetrievalCandidate],
    ranked_lists: list[list[RetrievalCandidate]],
    *,
    limit: int,
    per_list: int,
    expand_overlapping: bool = False,
) -> list[RetrievalCandidate]:
    """Reserve bounded list heads, then fill and order by the original RRF rank.

    A hit unique to one channel/query must reach the relevance judge even when
    several weaker hits have consensus. This changes admission, not RRF scores.
    """
    if limit <= 0 or per_list < 0:
        raise ValueError("coverage limit must be positive and per_list non-negative")
    lists = [ranked for ranked in ranked_lists if ranked]
    quota = min(per_list, limit // len(lists)) if lists else 0
    available = {_candidate_key(candidate) for candidate in fused}
    selected = {
        _candidate_key(candidate)
        for ranked in lists
        for candidate in ranked[:quota]
        if _candidate_key(candidate) in available
    }
    # Shared heads leave free slots. For query coverage, deepen all prefixes
    # together while their deduplicated union fits, before filling by consensus.
    if expand_overlapping and quota:
        maximum = max(map(len, lists))
        while len(selected) < limit and quota < maximum:
            next_selected = {
                _candidate_key(candidate)
                for ranked in lists
                for candidate in ranked[: quota + 1]
                if _candidate_key(candidate) in available
            }
            if len(next_selected) > limit:
                break
            selected = next_selected
            quota += 1
    for candidate in fused:
        if len(selected) >= limit:
            break
        selected.add(_candidate_key(candidate))
    return [candidate for candidate in fused if _candidate_key(candidate) in selected]


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
                    "metadata": {
                        **existing.metadata,
                        **(
                            {
                                "structural_parent_headings": candidate.metadata[
                                    "structural_parent_headings"
                                ]
                            }
                            if candidate.metadata.get("structural_parent_headings")
                            else {}
                        ),
                    },
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


__all__ = ["retain_list_coverage", "rrf_fuse"]
