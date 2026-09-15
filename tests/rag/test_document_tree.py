from __future__ import annotations

from hashlib import sha256

from backend.rag.document_tree import DocumentTreeBuilder
from backend.rag.models import (
    DocumentPage,
    DocumentSection,
    KnowledgeDocument,
    NormalizedDocument,
)


def _document(
    text: str,
    *,
    sections: list[DocumentSection],
    pages: list[DocumentPage] | None = None,
) -> NormalizedDocument:
    digest = sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id=f"doc_{digest[:24]}",
            title="Paper",
            source_uri="file:///paper.pdf",
            source_kind="pdf",
            mime_type="application/pdf",
            content_hash=digest,
        ),
        text=text,
        sections=sections,
        pages=pages or [],
    )


def _section(
    text: str,
    heading: str,
    level: int,
    start: int,
    end: int,
) -> DocumentSection:
    return DocumentSection(
        heading=heading,
        level=level,
        text=text[start:end],
        start_char=start,
        end_char=end,
    )


def test_builds_section_paths_from_heading_levels() -> None:
    text = (
        "3 Methodology\n\nOverview.\n\n"
        "3.1 Process Model\n\nModel paragraph.\n\n"
        "3.1.1 Tank Dynamics\n\nDynamics paragraph.\n\n"
        "3.2 Controller\n\nController paragraph."
    )
    sub_1 = text.index("3.1 Process Model")
    sub_11 = text.index("3.1.1 Tank Dynamics")
    sub_2 = text.index("3.2 Controller")
    sections = [
        _section(text, "3 Methodology", 1, 0, sub_1),
        _section(text, "3.1 Process Model", 2, sub_1, sub_11),
        _section(text, "3.1.1 Tank Dynamics", 3, sub_11, sub_2),
        _section(text, "3.2 Controller", 2, sub_2, len(text)),
    ]

    tree = DocumentTreeBuilder.build(_document(text, sections=sections))

    assert [node.section_path for node in tree.sections] == [
        ("3 Methodology",),
        ("3 Methodology", "3.1 Process Model"),
        ("3 Methodology", "3.1 Process Model", "3.1.1 Tank Dynamics"),
        ("3 Methodology", "3.2 Controller"),
    ]
    assert tree.sections[1].parent_section_id == tree.sections[0].node_id
    assert tree.sections[2].parent_section_id == tree.sections[1].node_id
    assert tree.sections[3].parent_section_id == tree.sections[0].node_id


def test_retains_paragraphs_as_atomic_source_spans() -> None:
    text = "Introduction\n\nFirst paragraph.\n\nSecond paragraph."
    sections = [_section(text, "Introduction", 1, 0, len(text))]

    tree = DocumentTreeBuilder.build(_document(text, sections=sections))
    paragraphs = tree.sections[0].paragraphs

    assert [paragraph.text for paragraph in paragraphs] == [
        "Introduction",
        "First paragraph.",
        "Second paragraph.",
    ]
    assert [paragraph.block_type for paragraph in paragraphs] == [
        "heading",
        "paragraph",
        "paragraph",
    ]
    assert all(text[p.start_char : p.end_char] == p.text for p in paragraphs)
    assert [p.paragraph_index for p in paragraphs] == [0, 1, 2]


def test_classifies_table_figure_and_equation_blocks() -> None:
    text = (
        "4 Results\n\n"
        "Table 2. Method comparison.\n\n"
        "| Method | J |\n|---|---|\n| M10 | 0.40 |\n\n"
        "Fig. 3. Closed-loop response.\n\n"
        "The response settles quickly.\n\n"
        "$$\nJ = IAE + 0.1 U\n$$"
    )
    sections = [_section(text, "4 Results", 1, 0, len(text))]

    blocks = DocumentTreeBuilder.build(_document(text, sections=sections)).sections[0].paragraphs

    assert [block.block_type for block in blocks] == [
        "heading",
        "table_caption",
        "table",
        "figure_caption",
        "paragraph",
        "equation",
    ]
    assert blocks[1].label.lower().startswith("table 2")
    assert blocks[3].label.lower().startswith("fig. 3")
    assert blocks[5].label == "equation"


def test_reference_section_is_split_into_reference_entries() -> None:
    text = (
        "6. References\n\n"
        "[1] A. Author, First paper.\n"
        "[2] B. Author, Second paper.\n"
        "[3] C. Author, Third paper."
    )
    sections = [_section(text, "6. References", 1, 0, len(text))]

    section = DocumentTreeBuilder.build(_document(text, sections=sections)).sections[0]
    entries = [block for block in section.paragraphs if block.block_type == "reference_entry"]

    assert section.metadata["reference_section"] is True
    assert [entry.label for entry in entries] == ["[1]", "[2]", "[3]"]
    assert [entry.text for entry in entries] == [
        "[1] A. Author, First paper.",
        "[2] B. Author, Second paper.",
        "[3] C. Author, Third paper.",
    ]
    assert all(text[item.start_char : item.end_char] == item.text for item in entries)


def test_paragraph_nodes_retain_page_ranges() -> None:
    first = "Introduction\n\nFirst page paragraph."
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
    sections = [_section(text, "Introduction", 1, 0, len(text))]

    tree = DocumentTreeBuilder.build(
        _document(text, sections=sections, pages=pages)
    )

    assert tree.sections[0].paragraphs[-1].page_start == 2
    assert tree.sections[0].paragraphs[-1].page_end == 2


def test_document_without_headings_uses_a_synthetic_root_region() -> None:
    text = "First paragraph.\n\nSecond paragraph."

    tree = DocumentTreeBuilder.build(_document(text, sections=[]))

    assert len(tree.sections) == 1
    assert tree.sections[0].synthetic is True
    assert tree.sections[0].section_path == ()
    assert [p.text for p in tree.sections[0].paragraphs] == [
        "First paragraph.",
        "Second paragraph.",
    ]
