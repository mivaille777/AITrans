from __future__ import annotations

from hashlib import sha256

import pytest

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagChunkingConfig, RagSemanticChunkingConfig
from backend.rag.models import DocumentSection, KnowledgeDocument, NormalizedDocument
from backend.rag.semantic_chunking import (
    SEMANTIC_CHUNKER_VERSION,
    SemanticStructureAwareChunker,
)


class TopicEmbedding:
    dimension = 2
    model_name = "fake-semantic"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("semantic embedding failed")
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            if "TOPIC_B" in text:
                vectors.append([0.0, 1.0])
            elif "TOPIC_MIX" in text:
                vectors.append([0.7, 0.7])
            else:
                vectors.append([1.0, 0.0])
        return vectors


def _section(text: str, heading: str, start: int, end: int, level: int = 1) -> DocumentSection:
    return DocumentSection(
        heading=heading,
        level=level,
        text=text[start:end],
        start_char=start,
        end_char=end,
    )


def _document(text: str, sections: list[DocumentSection]) -> NormalizedDocument:
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id=f"doc_{content_hash[:16]}",
            title="Semantic Test Paper",
            source_uri="file:///semantic-test.pdf",
            source_kind="pdf",
            mime_type="application/pdf",
            language="en",
            content_hash=content_hash,
        ),
        text=text,
        sections=sections,
        metadata={"parser_version": "test-parser-v1"},
    )


def _chunker(
    embedding: TopicEmbedding,
    *,
    target: int = 40,
    preferred: int = 50,
    hard: int = 70,
    minimum: int = 2,
    adaptive: bool = False,
) -> SemanticStructureAwareChunker:
    structural = StructureAwareChunker(
        RagChunkingConfig(
            target_tokens=target,
            preferred_max_tokens=preferred,
            hard_max_tokens=hard,
            overlap_tokens=1,
            minimum_tokens=minimum,
        )
    )
    return SemanticStructureAwareChunker(
        base_chunker=structural,
        semantic_config=RagSemanticChunkingConfig(
            enabled=True,
            adaptive_threshold_enabled=adaptive,
            merge_similarity=0.72,
            strong_merge_similarity=0.82,
            strong_split_similarity=0.58,
            small_chunk_merge_similarity=0.78,
            min_paragraphs_for_adaptive=4,
            centroid_window=4,
        ),
        embedding_provider=embedding,
    )


def test_semantic_topic_shift_splits_before_token_target() -> None:
    text = (
        "Methods\n\n"
        "TOPIC_A gaussian process localization.\n\n"
        "TOPIC_A posterior uncertainty guides search.\n\n"
        "TOPIC_B language model reads controller state.\n\n"
        "TOPIC_B local refinement follows mechanism evidence."
    )
    section = _section(text, "Methods", 0, len(text))
    embedding = TopicEmbedding()

    chunks = _chunker(embedding, target=80, preferred=90, hard=100).chunk(
        _document(text, [section])
    )

    assert len(chunks) == 2
    assert "TOPIC_A" in chunks[0].text
    assert "TOPIC_B" not in chunks[0].text
    assert chunks[1].text.startswith("TOPIC_B")
    assert chunks[1].metadata["semantic_boundary_reason"] == "strong_semantic_split"
    assert chunks[0].metadata["semantic_chunking_applied"] is True
    assert chunks[0].chunker_version == SEMANTIC_CHUNKER_VERSION
    assert chunks[0].metadata["semantic_cohesion"] == pytest.approx(1.0)
    assert len(embedding.calls) == 1
    assert len(embedding.calls[0]) == 4


def test_semantic_grouping_never_crosses_section_boundary() -> None:
    text = (
        "Introduction\n\n"
        "TOPIC_A one shared scientific topic.\n\n"
        "Methods\n\n"
        "TOPIC_A the same topic continues here."
    )
    methods = text.index("Methods")
    sections = [
        _section(text, "Introduction", 0, methods),
        _section(text, "Methods", methods, len(text)),
    ]

    chunks = _chunker(TopicEmbedding(), target=100, preferred=110, hard=120).chunk(
        _document(text, sections)
    )

    assert len(chunks) == 2
    assert [chunk.section_heading for chunk in chunks] == ["Introduction", "Methods"]
    assert "Methods" not in chunks[0].text
    assert chunks[1].text.startswith("Methods")


def test_strong_semantic_merge_can_exceed_preferred_but_not_hard_limit() -> None:
    text = (
        "Methods\n\n"
        "TOPIC_A one two three four five six.\n\n"
        "TOPIC_A seven eight nine ten eleven twelve."
    )
    section = _section(text, "Methods", 0, len(text))

    chunks = _chunker(
        TopicEmbedding(),
        target=8,
        preferred=10,
        hard=20,
        minimum=1,
    ).chunk(_document(text, [section]))

    assert len(chunks) == 1
    assert chunks[0].token_count > 10
    assert chunks[0].token_count <= 20
    assert "one two three" in chunks[0].text
    assert "seven eight nine" in chunks[0].text


def test_special_table_chunk_is_preserved_and_not_semantically_regrouped() -> None:
    text = (
        "Results\n\n"
        "TOPIC_A before table explanation.\n\n"
        "Table 2. Comparison.\n\n"
        "| Method | J |\n|---|---|\n| M10 | 0.40 |\n\n"
        "TOPIC_A after table explanation."
    )
    section = _section(text, "Results", 0, len(text))

    chunks = _chunker(TopicEmbedding(), target=30, preferred=40, hard=60).chunk(
        _document(text, [section])
    )

    tables = [chunk for chunk in chunks if chunk.chunk_type == "table"]
    assert len(tables) == 1
    assert "Table 2" in tables[0].text
    assert "| M10 | 0.40 |" in tables[0].text
    assert tables[0].metadata["boundary_strategy"] == "table_block"
    assert tables[0].chunker_version == SEMANTIC_CHUNKER_VERSION


def test_semantic_embedding_failure_degrades_to_structural_chunks() -> None:
    text = "Methods\n\nTOPIC_A first paragraph.\n\nTOPIC_B second paragraph."
    section = _section(text, "Methods", 0, len(text))

    chunks = _chunker(TopicEmbedding(fail=True), target=80, preferred=90, hard=100).chunk(
        _document(text, [section])
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["boundary_strategy"] == "paragraph_group"
    assert chunks[0].metadata["semantic_chunking_enabled"] is True
    assert chunks[0].metadata["semantic_chunking_applied"] is False
    assert "semantic embedding failed" in chunks[0].metadata["semantic_chunking_fallback_reason"]
    assert chunks[0].chunker_version == SEMANTIC_CHUNKER_VERSION


def test_semantic_metadata_exposes_boundary_and_cohesion_for_inspection() -> None:
    text = (
        "Discussion\n\n"
        "TOPIC_A first argument.\n\n"
        "TOPIC_A second argument.\n\n"
        "TOPIC_B different conclusion."
    )
    section = _section(text, "Discussion", 0, len(text))

    chunks = _chunker(TopicEmbedding(), target=80, preferred=90, hard=100).chunk(
        _document(text, [section])
    )

    first, second = chunks
    assert first.metadata["semantic_group_id"].startswith("semantic_")
    assert first.metadata["semantic_break_after"] == pytest.approx(0.0)
    assert second.metadata["semantic_break_before"] == pytest.approx(0.0)
    assert second.metadata["semantic_boundary_reason"] == "strong_semantic_split"
    assert 0.0 <= first.metadata["semantic_cohesion"] <= 1.0
