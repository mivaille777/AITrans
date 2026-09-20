from __future__ import annotations

from backend.rag.document_tree import DocumentTreeBuilder
from backend.rag.parsers.text import TextDocumentParser


def test_markdown_outline_preserves_heading_hierarchy_without_blank_synthetic_nodes(tmp_path) -> None:
    source = tmp_path / "outline.md"
    source.write_text(
        "# Project\n\n"
        "Intro text.\n\n"
        "## Phase 1\n\n"
        "Phase text.\n\n"
        "### Task 1.1\n\n"
        "Task text.\n\n"
        "## Phase 2\n\n"
        "More text.\n",
        encoding="utf-8",
    )

    document = TextDocumentParser().parse(source)
    tree = DocumentTreeBuilder.build(document)

    assert [section.heading for section in tree.sections] == [
        "Project",
        "Phase 1",
        "Task 1.1",
        "Phase 2",
    ]
    assert [section.level for section in tree.sections] == [1, 2, 3, 2]
    assert all(not section.synthetic for section in tree.sections)
    assert tree.sections[1].parent_section_id == tree.sections[0].node_id
    assert tree.sections[2].parent_section_id == tree.sections[1].node_id
    assert tree.sections[3].parent_section_id == tree.sections[0].node_id
