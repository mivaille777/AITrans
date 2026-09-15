from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from itertools import pairwise

from backend.rag.chunking import CHUNKER_VERSION, StructureAwareChunker, chunk_document
from backend.rag.config import RagChunkingConfig
from backend.rag.models import (
    DocumentPage,
    DocumentSection,
    KnowledgeDocument,
    NormalizedDocument,
)


def make_document(
    text: str,
    *,
    sections: list[DocumentSection] | None = None,
    pages: list[DocumentPage] | None = None,
    language: str = "unknown",
) -> NormalizedDocument:
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id=f"doc_{content_hash[:24]}",
            title="Test Paper",
            source_uri="file:///test-paper.md",
            source_kind="markdown",
            mime_type="text/markdown",
            language=language,
            content_hash=content_hash,
            metadata={"author": "Tester"},
        ),
        text=text,
        sections=sections or [],
        pages=pages or [],
        metadata={"parser_name": "test", "parser_version": "test-v1"},
    )


def make_chunker(
    *,
    target: int = 12,
    preferred: int | None = None,
    hard: int | None = None,
    overlap: int = 3,
    minimum: int = 4,
) -> StructureAwareChunker:
    return StructureAwareChunker(
        RagChunkingConfig(
            target_tokens=target,
            preferred_max_tokens=preferred,
            hard_max_tokens=hard,
            overlap_tokens=overlap,
            minimum_tokens=minimum,
        )
    )


def section_for(
    text: str,
    heading: str,
    start: int,
    end: int,
    *,
    level: int = 1,
) -> DocumentSection:
    return DocumentSection(
        heading=heading,
        level=level,
        text=text[start:end],
        start_char=start,
        end_char=end,
        metadata={"kind": "section"},
    )


def test_small_single_section_document_produces_one_chunk() -> None:
    text = "Introduction\n\nGaussian processes guide PID tuning."
    section = section_for(text, "Introduction", 0, len(text))

    chunks = make_chunker(target=30, overlap=4, minimum=5).chunk(
        make_document(text, sections=[section])
    )

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].section_heading == "Introduction"
    assert chunks[0].section_path == ["Introduction"]
    assert chunks[0].chunker_version == CHUNKER_VERSION
    assert chunks[0].metadata["boundary_strategy"] == "paragraph_group"


def test_section_and_subsection_paths_are_preserved_on_chunks() -> None:
    text = (
        "3 Methodology\n\nOverview.\n\n"
        "3.1 Process Model\n\nModel paragraph.\n\n"
        "3.1.1 Dynamics\n\nDynamics paragraph."
    )
    sub = text.index("3.1 Process Model")
    nested = text.index("3.1.1 Dynamics")
    sections = [
        section_for(text, "3 Methodology", 0, sub, level=1),
        section_for(text, "3.1 Process Model", sub, nested, level=2),
        section_for(text, "3.1.1 Dynamics", nested, len(text), level=3),
    ]

    chunks = make_chunker(target=40, overlap=4, minimum=3).chunk(
        make_document(text, sections=sections)
    )

    assert chunks[0].section_path == ["3 Methodology"]
    assert chunks[1].section_path == ["3 Methodology", "3.1 Process Model"]
    assert chunks[2].section_path == [
        "3 Methodology",
        "3.1 Process Model",
        "3.1.1 Dynamics",
    ]
    assert chunks[2].hierarchy_level == 3
    assert chunks[1].parent_section_id


def test_multiple_sections_are_never_combined_even_when_short() -> None:
    text = "Introduction\n\nShort background.\n\nMethods\n\nShort method."
    methods_start = text.index("Methods")
    sections = [
        section_for(text, "Introduction", 0, methods_start),
        section_for(text, "Methods", methods_start, len(text)),
    ]

    chunks = make_chunker(target=100, preferred=120, hard=160, overlap=10, minimum=10).chunk(
        make_document(text, sections=sections)
    )

    assert [chunk.section_heading for chunk in chunks] == ["Introduction", "Methods"]
    assert "Methods" not in chunks[0].text
    assert chunks[1].text.startswith("Methods")


def test_complete_paragraphs_are_grouped_before_token_fallback() -> None:
    text = (
        "Methods\n\n"
        "alpha beta gamma delta\n\n"
        "epsilon zeta eta theta\n\n"
        "iota kappa lambda mu"
    )
    section = section_for(text, "Methods", 0, len(text))

    chunks = make_chunker(
        target=8,
        preferred=10,
        hard=14,
        overlap=2,
        minimum=2,
    ).chunk(make_document(text, sections=[section]))

    assert len(chunks) == 2
    assert chunks[0].text == "Methods\n\nalpha beta gamma delta\n\nepsilon zeta eta theta"
    assert chunks[1].text == "iota kappa lambda mu"
    assert chunks[0].paragraph_index == 0
    assert chunks[0].paragraph_end_index == 2
    assert chunks[1].paragraph_index == 3
    assert chunks[0].end_char < chunks[1].start_char


def test_normal_paragraph_chunks_do_not_use_mechanical_overlap() -> None:
    text = (
        "Heading\n\n"
        "one two three four\n\n"
        "five six seven eight\n\n"
        "nine ten eleven twelve"
    )
    section = section_for(text, "Heading", 0, len(text))

    chunks = make_chunker(
        target=6,
        preferred=7,
        hard=10,
        overlap=3,
        minimum=2,
    ).chunk(make_document(text, sections=[section]))

    assert len(chunks) >= 2
    for previous, current in pairwise(chunks):
        if (
            previous.metadata["boundary_strategy"] == "paragraph_group"
            and current.metadata["boundary_strategy"] == "paragraph_group"
        ):
            assert current.start_char >= previous.end_char


def test_heading_stays_with_body_when_first_paragraph_requires_fallback() -> None:
    text = "Methods\n\n" + " ".join(f"detail{index}" for index in range(30))
    section = section_for(text, "Methods", 0, len(text))

    chunks = make_chunker(target=8, hard=8, overlap=2, minimum=1).chunk(
        make_document(text, sections=[section])
    )

    assert chunks[0].text.startswith("Methods\n\n")
    assert chunks[0].text != "Methods"
    assert chunks[0].metadata["boundary_strategy"] == "sentence_fallback"


def test_long_paragraph_uses_sentence_or_token_fallback_with_bounded_chunks() -> None:
    text = " ".join(f"word{index}" for index in range(80))

    chunks = make_chunker(target=12, hard=12, overlap=3, minimum=4).chunk(
        make_document(text)
    )

    assert len(chunks) > 2
    assert all(chunk.token_count <= 12 for chunk in chunks)
    assert all(chunk.metadata["boundary_strategy"] == "sentence_fallback" for chunk in chunks)
    assert chunks[0].start_char == 0
    assert chunks[-1].end_char == len(text)


def test_overlap_is_only_retained_inside_oversized_paragraph_fallback() -> None:
    text = " ".join(f"term{index}" for index in range(40))

    chunks = make_chunker(target=10, hard=10, overlap=3, minimum=3).chunk(
        make_document(text)
    )

    for previous, current in pairwise(chunks):
        assert current.start_char < previous.end_char
        shared = text[current.start_char : previous.end_char].strip()
        assert 0 < make_chunker().token_counter.count(shared) <= 3


def test_overlap_is_retained_for_chinese_fallback_without_spaces() -> None:
    text = "甲乙丙丁戊己庚辛壬癸" * 4

    chunks = make_chunker(target=10, hard=10, overlap=3, minimum=3).chunk(
        make_document(text)
    )

    assert len(chunks) > 1
    for previous, current in pairwise(chunks):
        assert current.start_char < previous.end_char
        shared = text[current.start_char : previous.end_char]
        assert 0 < make_chunker().token_counter.count(shared) <= 3


def test_page_number_and_page_range_are_retained() -> None:
    first = "First page paragraph."
    second = "Second page paragraph."
    text = f"{first}\n\n{second}"
    pages = [
        DocumentPage(page_number=1, text=first, start_char=0, end_char=len(first)),
        DocumentPage(
            page_number=2,
            text=second,
            start_char=len(first) + 2,
            end_char=len(text),
        ),
    ]

    chunk = make_chunker(target=30, preferred=40, hard=50, overlap=3, minimum=3).chunk(
        make_document(text, pages=pages)
    )[0]

    assert chunk.page_number == 1
    assert chunk.metadata["page_start"] == 1
    assert chunk.metadata["page_end"] == 2


def test_character_offsets_slice_the_original_text_exactly() -> None:
    text = "Alpha paragraph.\n\nBeta paragraph has more words.\n\nGamma paragraph."

    chunks = make_chunker(target=8, hard=12, overlap=2, minimum=2).chunk(
        make_document(text)
    )

    assert all(text[chunk.start_char : chunk.end_char] == chunk.text for chunk in chunks)
    assert [chunk.start_char for chunk in chunks] == sorted(chunk.start_char for chunk in chunks)


def test_chunk_ids_are_stable_and_change_with_content() -> None:
    text = "Stable chunk input with enough words for a deterministic identifier."
    chunker = make_chunker(target=30, hard=40, overlap=3, minimum=3)

    first = chunker.chunk(make_document(text))
    repeated = chunker.chunk(make_document(text))
    changed = chunker.chunk(make_document(f"{text} Changed."))

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in repeated]
    assert first[0].chunk_id != changed[0].chunk_id


def test_same_input_is_fully_deterministic() -> None:
    text = "One sentence. Two sentence. 三个句子。四个句子。" * 5
    document = make_document(text)
    chunker = make_chunker(target=10, hard=14, overlap=2, minimum=3)

    first = chunker.chunk(document)
    second = chunker.chunk(document)

    assert [chunk.model_dump() for chunk in first] == [
        chunk.model_dump() for chunk in second
    ]


def test_empty_document_returns_empty_list() -> None:
    document = make_document("")

    assert chunk_document(document) == []


def test_chunking_does_not_modify_normalized_document() -> None:
    text = "Heading\n\nFirst paragraph.\n\nSecond paragraph with more content."
    document = make_document(
        text,
        sections=[section_for(text, "Heading", 0, len(text))],
    )
    original = deepcopy(document).model_dump()

    make_chunker(target=7, hard=12, overlap=2, minimum=2).chunk(document)

    assert document.model_dump() == original


def test_source_parser_and_hierarchy_metadata_are_preserved() -> None:
    text = "A compact source metadata example."

    chunk = make_chunker(target=20, hard=25, overlap=2, minimum=2).chunk(
        make_document(text)
    )[0]

    assert chunk.document_hash == sha256(text.encode("utf-8")).hexdigest()
    assert chunk.parser_version == "test-v1"
    assert chunk.metadata["source_kind"] == "markdown"
    assert chunk.metadata["document_metadata"] == {"author": "Tester"}
    assert chunk.metadata["section_path"] == []
    assert chunk.metadata["paragraph_start"] == 0
    assert chunk.metadata["paragraph_end"] == 0
