from backend.rag.fusion import retain_list_coverage, rrf_fuse
from backend.rag.models import DocumentChunk, RetrievalCandidate


def hit(chunk_id, generation):
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id="doc",
            text=chunk_id,
            chunk_index=0,
            metadata={"index_generation": generation},
        ),
        index_generation=generation,
    )


def test_same_id_in_distinct_generations_does_not_alias_coverage_slots():
    a, b = hit("same", "active"), hit("same", "retired")
    ranked = [[a], [b]]
    fused = rrf_fuse(ranked, limit=2)
    selected = retain_list_coverage(fused, ranked, limit=2, per_list=1)
    assert {c.index_generation for c in selected} == {"active", "retired"}
    assert selected == fused


def test_budget_too_small_for_all_channels_keeps_rrf_order():
    ranked = [[hit("one", "active")], [hit("two", "active")]]
    fused = rrf_fuse(ranked, limit=2)
    assert retain_list_coverage(fused, ranked, limit=1, per_list=1) == fused[:1]
    assert retain_list_coverage([], [], limit=1, per_list=1) == []


def test_shared_query_heads_free_capacity_for_complementary_third_rank():
    ranked = [
        [hit(f"original-{i}", "active") for i in range(8)],
        [hit(f"shared-{i}", "active") for i in range(8)],
        [
            hit("shared-0", "active"),
            hit("shared-2", "active"),
            hit("explanation", "active"),
            *[hit(f"shared-{i}", "active") for i in [3, 4, 5, 6, 7]],
        ],
    ]
    fused = rrf_fuse(ranked, limit=17)
    selected = retain_list_coverage(
        fused,
        ranked,
        limit=8,
        per_list=2,
        expand_overlapping=True,
    )
    assert len(selected) == 8
    assert "explanation" in {c.chunk.chunk_id for c in selected}
    assert [c.fusion_score for c in selected] == sorted(
        [c.fusion_score for c in selected],
        reverse=True,
    )
