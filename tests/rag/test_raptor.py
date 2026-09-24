from __future__ import annotations

import json

from backend.rag.models import DocumentChunk
from backend.rag.raptor import RaptorTreeBuilder


class _FakeEmbedding:
    dimension = 3
    model_name = "fake-raptor-embedding"

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, float(index % 2), 0.0] for index, _text in enumerate(texts)]


class _FakeSummaryProvider:
    model_name = "fake-summary-model"
    prompt_version = "fake-summary-v1"

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, children, *, level: int) -> str:
        self.calls += 1
        return f"Level {level}: " + " ".join(child.text for child in children)


def _chunks(count: int) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            chunk_id=f"chunk-{index}",
            document_id="paper-1",
            text=f"Evidence paragraph {index} describes a result.",
            title="Paper",
            section_heading=f"Section {index // 3}",
            section_path=[f"Section {index // 3}"],
            chunk_index=index,
            metadata={
                "benchmark": {"source_paragraph_ids": [f"paper-1:p{index}"]}
            },
        )
        for index in range(count)
    ]


def test_raptor_tree_recursively_clusters_and_preserves_leaf_provenance(tmp_path) -> None:
    embedding = _FakeEmbedding()
    summaries = _FakeSummaryProvider()
    tree = RaptorTreeBuilder(
        embedding_provider=embedding,
        summary_provider=summaries,
        cache_directory=tmp_path,
        branching_factor=2,
    ).build(_chunks(9))

    assert tree.cache_hit is False
    assert summaries.calls == tree.summary_calls
    assert len(tree.nodes) > 9
    assert max(node.level for node in tree.nodes) >= 3
    root = next(node for node in tree.nodes if node.node_id == tree.root_node_ids[0])
    assert set(root.descendant_chunk_ids) == {chunk.chunk_id for chunk in _chunks(9)}
    assert set(root.descendant_paragraph_ids) == {
        f"paper-1:p{index}" for index in range(9)
    }
    assert all(node.model == summaries.model_name for node in tree.nodes)
    assert all(node.prompt_version == summaries.prompt_version for node in tree.nodes)
    assert all(node.embedding_model == embedding.model_name for node in tree.nodes)


def test_raptor_tree_cache_reuses_summaries_without_query_parameters(tmp_path) -> None:
    embedding = _FakeEmbedding()
    first_summarizer = _FakeSummaryProvider()
    first = RaptorTreeBuilder(
        embedding_provider=embedding,
        summary_provider=first_summarizer,
        cache_directory=tmp_path,
        branching_factor=3,
    ).build(_chunks(7))

    second_summarizer = _FakeSummaryProvider()
    second = RaptorTreeBuilder(
        embedding_provider=embedding,
        summary_provider=second_summarizer,
        cache_directory=tmp_path,
        branching_factor=3,
    ).build(_chunks(7))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.fingerprint == first.fingerprint
    assert second.summary_calls == first.summary_calls
    assert second_summarizer.calls == 0
    assert [node.as_dict() for node in second.nodes] == [
        node.as_dict() for node in first.nodes
    ]


def test_raptor_tree_rejects_mixed_document_leaves(tmp_path) -> None:
    chunks = _chunks(2)
    chunks[1] = chunks[1].model_copy(update={"document_id": "paper-2"})

    builder = RaptorTreeBuilder(
        embedding_provider=_FakeEmbedding(),
        summary_provider=_FakeSummaryProvider(),
        cache_directory=tmp_path,
    )

    try:
        builder.build(chunks)
    except ValueError as exc:
        assert "one document" in str(exc)
    else:
        raise AssertionError("mixed-document RAPTOR leaves should be rejected")


def test_raptor_tree_rebuilds_cache_with_invalid_leaf_reference(tmp_path) -> None:
    builder = RaptorTreeBuilder(
        embedding_provider=_FakeEmbedding(),
        summary_provider=_FakeSummaryProvider(),
        cache_directory=tmp_path,
        branching_factor=2,
    )
    first = builder.build(_chunks(5))
    payload = json.loads(first.cache_path.read_text(encoding="utf-8"))
    payload["nodes"][0]["descendant_chunk_ids"] = ["another-paper-chunk"]
    first.cache_path.write_text(json.dumps(payload), encoding="utf-8")

    rebuilt = builder.build(_chunks(5))

    assert rebuilt.cache_hit is False
    assert all(
        set(node.descendant_chunk_ids) <= {chunk.chunk_id for chunk in _chunks(5)}
        for node in rebuilt.nodes
    )
