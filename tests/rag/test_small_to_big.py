from __future__ import annotations

from backend.rag.config import RagRetrievalConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.small_to_big import SmallToBigContextExpander


class WordCounter:
    def count(self, text: str) -> int:
        return len(text.split())


def chunk(
    chunk_id: str,
    index: int,
    text: str,
    *,
    chunk_type: str = "paragraph_group",
    section_path: list[str] | None = None,
    start: int | None = None,
) -> DocumentChunk:
    start_char = index * 100 if start is None else start
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="paper",
        title="Paper",
        text=text,
        section_heading="3.2 Method",
        section_path=section_path or ["3 Methodology", "3.2 Method"],
        chunk_type=chunk_type,
        page_number=5 + index,
        chunk_index=index,
        start_char=start_char,
        end_char=start_char + len(text),
        token_count=len(text.split()),
    )


def test_expands_top_child_with_same_section_neighbors_without_changing_rank() -> None:
    previous = chunk("previous", 0, "previous context")
    anchor = chunk("anchor", 1, "precise matched child")
    following = chunk("following", 2, "following explanation")
    candidates = [RetrievalCandidate(chunk=anchor, rank=1, rerank_score=0.9)]

    expander = SmallToBigContextExpander(
        neighbor_lookup=lambda _anchor, _radius: [previous, anchor, following],
        config=RagRetrievalConfig(
            small_to_big_top_k=1,
            small_to_big_neighbor_radius=1,
            small_to_big_max_tokens_per_anchor=20,
        ),
        token_counter=WordCounter(),
    )

    expanded, metadata = expander.expand(candidates)

    assert len(expanded) == 1
    assert expanded[0].rank == 1
    assert expanded[0].chunk.chunk_id == "anchor"
    assert expanded[0].context_window is not None
    assert [item.chunk_id for item in expanded[0].context_window.chunks] == [
        "previous",
        "anchor",
        "following",
    ]
    assert "previous context" in expanded[0].context_window.text
    assert "precise matched child" in expanded[0].context_window.text
    assert "following explanation" in expanded[0].context_window.text
    assert metadata["small_to_big_expanded_count"] == 1
    assert metadata["small_to_big_neighbor_count"] == 2


def test_special_blocks_are_not_expanded() -> None:
    table = chunk("table", 1, "Table 2 | M10 | 0.40", chunk_type="table")
    calls = []

    def lookup(anchor, radius):
        calls.append((anchor, radius))
        return [table]

    expanded, metadata = SmallToBigContextExpander(
        neighbor_lookup=lookup,
        config=RagRetrievalConfig(),
        token_counter=WordCounter(),
    ).expand([RetrievalCandidate(chunk=table, rank=1)])

    assert calls == []
    assert expanded[0].context_window is None
    assert metadata["small_to_big_expanded_count"] == 0


def test_expansion_never_crosses_leaf_section() -> None:
    anchor = chunk("anchor", 1, "anchor text")
    wrong_section = chunk(
        "wrong",
        2,
        "other section text",
        section_path=["3 Methodology", "3.3 Other"],
    )

    expanded, _ = SmallToBigContextExpander(
        neighbor_lookup=lambda _anchor, _radius: [anchor, wrong_section],
        config=RagRetrievalConfig(),
        token_counter=WordCounter(),
    ).expand([RetrievalCandidate(chunk=anchor, rank=1)])

    assert expanded[0].context_window is None


def test_context_budget_keeps_anchor_and_nearest_fitting_neighbor() -> None:
    previous = chunk("previous", 0, "one two three four")
    anchor = chunk("anchor", 1, "five six seven")
    following = chunk("following", 2, "eight nine ten eleven")

    expanded, _ = SmallToBigContextExpander(
        neighbor_lookup=lambda _anchor, _radius: [previous, anchor, following],
        config=RagRetrievalConfig(
            small_to_big_top_k=1,
            small_to_big_max_tokens_per_anchor=7,
        ),
        token_counter=WordCounter(),
    ).expand([RetrievalCandidate(chunk=anchor, rank=1)])

    window = expanded[0].context_window
    assert window is not None
    assert window.anchor_chunk_id == "anchor"
    assert len(window.chunks) == 2
    assert window.token_count <= 7


def test_overlap_is_removed_when_neighbor_source_spans_overlap() -> None:
    first = chunk("first", 0, "Alpha Beta Gamma", start=0)
    # Original source would be "Alpha Beta Gamma Delta"; the second chunk starts
    # at the beginning of "Gamma", so the source spans overlap by five chars.
    second = chunk("second", 1, "Gamma Delta", start=len("Alpha Beta "))
    anchor = second

    expanded, _ = SmallToBigContextExpander(
        neighbor_lookup=lambda _anchor, _radius: [first, second],
        config=RagRetrievalConfig(
            small_to_big_top_k=1,
            small_to_big_max_tokens_per_anchor=20,
        ),
        token_counter=WordCounter(),
    ).expand([RetrievalCandidate(chunk=anchor, rank=1)])

    assert expanded[0].context_window is not None
    assert expanded[0].context_window.text.count("Gamma") == 1


def test_multiple_true_hits_do_not_duplicate_each_other_or_claimed_siblings() -> None:
    before = chunk("before", 0, "before context")
    first_hit = chunk("first-hit", 1, "first matched child")
    between = chunk("between", 2, "shared middle context")
    second_hit = chunk("second-hit", 3, "second matched child")
    after = chunk("after", 4, "after context")
    catalog = [before, first_hit, between, second_hit, after]

    def lookup(anchor, radius):
        position = catalog.index(next(item for item in catalog if item.chunk_id == anchor.chunk_id))
        return catalog[max(0, position - radius) : position + radius + 1]

    expanded, metadata = SmallToBigContextExpander(
        neighbor_lookup=lookup,
        config=RagRetrievalConfig(
            small_to_big_top_k=2,
            small_to_big_neighbor_radius=2,
            small_to_big_max_tokens_per_anchor=20,
        ),
        token_counter=WordCounter(),
    ).expand(
        [
            RetrievalCandidate(chunk=first_hit, rank=1),
            RetrievalCandidate(chunk=second_hit, rank=2),
        ]
    )

    first_window = expanded[0].context_window
    second_window = expanded[1].context_window
    assert first_window is not None
    assert "second-hit" not in {item.chunk_id for item in first_window.chunks}
    if second_window is not None:
        first_supplemental = {
            item.chunk_id for item in first_window.chunks if item.chunk_id != "first-hit"
        }
        second_supplemental = {
            item.chunk_id for item in second_window.chunks if item.chunk_id != "second-hit"
        }
        assert first_supplemental.isdisjoint(second_supplemental)
        assert "first-hit" not in {item.chunk_id for item in second_window.chunks}
    assert metadata["small_to_big_neighbor_count"] <= 3
