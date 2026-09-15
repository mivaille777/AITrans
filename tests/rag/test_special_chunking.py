from __future__ import annotations

from hashlib import sha256

from backend.rag.chunking import CHUNKER_VERSION, StructureAwareChunker
from backend.rag.config import RagChunkingConfig
from backend.rag.models import DocumentSection, KnowledgeDocument, NormalizedDocument


def _document(text: str, *, heading: str) -> NormalizedDocument:
    digest = sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id=f"doc_{digest[:24]}",
            title="Scientific Paper",
            source_uri="file:///paper.pdf",
            source_kind="pdf",
            mime_type="application/pdf",
            language="en",
            content_hash=digest,
        ),
        text=text,
        sections=[
            DocumentSection(
                heading=heading,
                level=1,
                text=text,
                start_char=0,
                end_char=len(text),
                metadata={"page_number": 1},
            )
        ],
        metadata={"parser_name": "docling", "parser_version": "docling-test"},
    )


def _chunker(*, target: int = 40, preferred: int = 80, hard: int = 120) -> StructureAwareChunker:
    return StructureAwareChunker(
        RagChunkingConfig(
            target_tokens=target,
            preferred_max_tokens=preferred,
            hard_max_tokens=hard,
            overlap_tokens=12,
            minimum_tokens=8,
        )
    )


def test_table_caption_and_markdown_table_form_one_table_chunk() -> None:
    text = (
        "4 Results\n\n"
        "Table 2. Method comparison.\n\n"
        "| Method | J |\n|---|---|\n| M10 | 0.40 |\n| C8 | 0.93 |"
    )

    chunks = _chunker().chunk(_document(text, heading="4 Results"))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_type == "table"
    assert chunk.chunker_version == CHUNKER_VERSION
    assert chunk.text == text
    assert chunk.section_path == ["4 Results"]
    assert chunk.metadata["boundary_strategy"] == "table_block"
    assert chunk.metadata["special_block"] is True
    assert "table_caption" in chunk.metadata["block_types"]
    assert "table" in chunk.metadata["block_types"]
    assert any(label.lower().startswith("table 2") for label in chunk.metadata["special_labels"])
    assert text[chunk.start_char : chunk.end_char] == chunk.text


def test_figure_caption_binds_the_immediate_explanatory_paragraph() -> None:
    text = (
        "4 Results\n\n"
        "Fig. 3. Closed-loop response under the proposed method.\n\n"
        "The response settles rapidly with low overshoot.\n\n"
        "A later paragraph discusses an unrelated ablation."
    )

    chunks = _chunker(target=25, preferred=45, hard=70).chunk(
        _document(text, heading="4 Results")
    )

    figure = next(chunk for chunk in chunks if chunk.chunk_type == "figure_context")
    assert figure.text.startswith("4 Results\n\nFig. 3.")
    assert "The response settles rapidly" in figure.text
    assert "unrelated ablation" not in figure.text
    assert figure.metadata["boundary_strategy"] == "figure_context"
    assert "figure_caption" in figure.metadata["block_types"]
    assert text[figure.start_char : figure.end_char] == figure.text


def test_equation_context_keeps_previous_equation_and_following_explanation_together() -> None:
    text = (
        "3 Methodology\n\n"
        "The controller state is introduced first.\n\n"
        "The complete objective is defined as follows.\n\n"
        "$$\nJ = IAE + 0.1 U\n$$\n\n"
        "where U penalizes excessive actuator movement."
    )

    chunks = _chunker(target=20, preferred=35, hard=70).chunk(
        _document(text, heading="3 Methodology")
    )

    equation = next(chunk for chunk in chunks if chunk.chunk_type == "equation_context")
    assert "The complete objective is defined as follows." in equation.text
    assert "J = IAE + 0.1 U" in equation.text
    assert "where U penalizes" in equation.text
    assert equation.metadata["boundary_strategy"] == "equation_context"
    assert "equation" in equation.metadata["block_types"]
    assert text[equation.start_char : equation.end_char] == equation.text


def test_reference_entries_are_grouped_without_losing_entry_boundaries() -> None:
    text = (
        "6. References\n\n"
        "[1] A. Author, First paper.\n"
        "[2] B. Author, Second paper.\n"
        "[3] C. Author, Third paper."
    )

    chunks = _chunker(target=50, preferred=90, hard=120).chunk(
        _document(text, heading="6. References")
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_type == "reference_group"
    assert chunk.text == text
    assert chunk.metadata["boundary_strategy"] == "reference_group"
    assert chunk.metadata["reference_entry_count"] == 3
    assert chunk.metadata["special_labels"] == ["[1]", "[2]", "[3]"]
    assert "reference_entry" in chunk.metadata["block_types"]
    assert text[chunk.start_char : chunk.end_char] == chunk.text


def test_special_chunks_preserve_exact_offsets_and_do_not_fall_back_to_plain_prose() -> None:
    text = (
        "5 Discussion\n\n"
        "Table 4. Robustness summary.\n\n"
        "| Case | Stable |\n|---|---|\n| Nominal | Yes |\n\n"
        "Fig. 5. Robustness response.\n\n"
        "The trajectory remains bounded."
    )

    chunks = _chunker(target=30, preferred=55, hard=80).chunk(
        _document(text, heading="5 Discussion")
    )

    assert [chunk.chunk_type for chunk in chunks] == ["table", "figure_context"]
    assert all(text[chunk.start_char : chunk.end_char] == chunk.text for chunk in chunks)
    assert all(chunk.section_heading == "5 Discussion" for chunk in chunks)
    assert all(chunk.section_path == ["5 Discussion"] for chunk in chunks)
