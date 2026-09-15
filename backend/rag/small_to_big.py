from __future__ import annotations

from collections.abc import Callable

from backend.rag.config import RagRetrievalConfig
from backend.rag.models import (
    DocumentChunk,
    RetrievalCandidate,
    RetrievalContextWindow,
)
from backend.rag.tokenization import HeuristicTokenCounter, TokenCounter

_EXPANDABLE_CHUNK_TYPES = frozenset({"paragraph_group"})


class SmallToBigContextExpander:
    """Attach bounded same-section context without changing retrieval rank.

    Only true retrieval candidates remain ranked evidence. Neighbor chunks are
    supplemental synthesis context and never become retrieval candidates on
    their own. Special academic blocks are already self-contained and are not
    expanded here.
    """

    def __init__(
        self,
        *,
        neighbor_lookup: Callable[[DocumentChunk, int], list[DocumentChunk]],
        config: RagRetrievalConfig | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._neighbor_lookup = neighbor_lookup
        self._config = config or RagRetrievalConfig()
        self._token_counter = token_counter or HeuristicTokenCounter()

    def expand(
        self,
        candidates: list[RetrievalCandidate],
    ) -> tuple[list[RetrievalCandidate], dict[str, int]]:
        if not self._config.small_to_big_enabled or not candidates:
            return candidates, {
                "small_to_big_expanded_count": 0,
                "small_to_big_neighbor_count": 0,
            }

        true_hit_ids = {candidate.chunk.chunk_id for candidate in candidates}
        claimed_supplemental_ids: set[str] = set()
        expanded: list[RetrievalCandidate] = []
        expanded_count = 0
        neighbor_count = 0
        for position, candidate in enumerate(candidates):
            if position >= self._config.small_to_big_top_k:
                expanded.append(candidate)
                continue
            excluded = (true_hit_ids - {candidate.chunk.chunk_id}) | claimed_supplemental_ids
            window = self._window_for(candidate.chunk, excluded_chunk_ids=excluded)
            if window is None or len(window.chunks) <= 1:
                expanded.append(candidate)
                continue
            supplemental_ids = {
                chunk.chunk_id
                for chunk in window.chunks
                if chunk.chunk_id != candidate.chunk.chunk_id
            }
            claimed_supplemental_ids.update(supplemental_ids)
            expanded_count += 1
            neighbor_count += len(supplemental_ids)
            metadata = dict(candidate.metadata)
            metadata.update(
                {
                    "small_to_big_expanded": True,
                    "small_to_big_context_chunk_ids": [
                        chunk.chunk_id for chunk in window.chunks
                    ],
                    "small_to_big_context_tokens": window.token_count,
                }
            )
            expanded.append(
                candidate.model_copy(
                    update={
                        "context_window": window,
                        "metadata": metadata,
                    }
                )
            )

        return expanded, {
            "small_to_big_expanded_count": expanded_count,
            "small_to_big_neighbor_count": neighbor_count,
        }

    def _window_for(
        self,
        anchor: DocumentChunk,
        *,
        excluded_chunk_ids: set[str],
    ) -> RetrievalContextWindow | None:
        if anchor.chunk_type not in _EXPANDABLE_CHUNK_TYPES:
            return None
        if not anchor.section_path:
            return None

        neighbors = self._neighbor_lookup(
            anchor,
            self._config.small_to_big_neighbor_radius,
        )
        unique: dict[str, DocumentChunk] = {anchor.chunk_id: anchor}
        for chunk in neighbors:
            if chunk.chunk_id in excluded_chunk_ids:
                continue
            if chunk.document_id != anchor.document_id:
                continue
            if chunk.section_path != anchor.section_path:
                continue
            if chunk.chunk_type not in _EXPANDABLE_CHUNK_TYPES:
                continue
            unique[chunk.chunk_id] = chunk

        ordered = sorted(unique.values(), key=lambda chunk: (chunk.chunk_index, chunk.chunk_id))
        if len(ordered) <= 1:
            return None
        selected = self._select_with_budget(anchor, ordered)
        if len(selected) <= 1:
            return None
        selected.sort(key=lambda chunk: (chunk.chunk_index, chunk.chunk_id))
        text = self._merge_source_spans(selected)
        pages = sorted(
            {chunk.page_number for chunk in selected if chunk.page_number is not None}
        )
        return RetrievalContextWindow(
            anchor_chunk_id=anchor.chunk_id,
            chunks=[chunk.model_copy(deep=True) for chunk in selected],
            text=text,
            token_count=self._token_counter.count(text),
            page_start=pages[0] if pages else None,
            page_end=pages[-1] if pages else None,
        )

    def _select_with_budget(
        self,
        anchor: DocumentChunk,
        ordered: list[DocumentChunk],
    ) -> list[DocumentChunk]:
        budget = self._config.small_to_big_max_tokens_per_anchor
        selected: dict[str, DocumentChunk] = {anchor.chunk_id: anchor}
        anchor_tokens = self._chunk_tokens(anchor)
        used = min(anchor_tokens, budget)
        others = sorted(
            (chunk for chunk in ordered if chunk.chunk_id != anchor.chunk_id),
            key=lambda chunk: (
                abs(chunk.chunk_index - anchor.chunk_index),
                chunk.chunk_index,
                chunk.chunk_id,
            ),
        )
        for chunk in others:
            tokens = self._chunk_tokens(chunk)
            if used + tokens > budget:
                continue
            selected[chunk.chunk_id] = chunk
            used += tokens
        return list(selected.values())

    def _chunk_tokens(self, chunk: DocumentChunk) -> int:
        return chunk.token_count or self._token_counter.count(chunk.text)

    @staticmethod
    def _merge_source_spans(chunks: list[DocumentChunk]) -> str:
        if not chunks:
            return ""
        ordered = sorted(chunks, key=lambda chunk: (chunk.start_char, chunk.chunk_index))
        text = ordered[0].text
        current_end = ordered[0].end_char
        for chunk in ordered[1:]:
            if chunk.start_char >= current_end:
                separator = "\n\n" if text and chunk.text else ""
                text += separator + chunk.text
                current_end = max(current_end, chunk.end_char)
                continue
            overlap_chars = max(0, current_end - chunk.start_char)
            suffix = chunk.text[overlap_chars:] if overlap_chars < len(chunk.text) else ""
            if suffix:
                text += suffix
            current_end = max(current_end, chunk.end_char)
        return text.strip()


__all__ = ["SmallToBigContextExpander"]
