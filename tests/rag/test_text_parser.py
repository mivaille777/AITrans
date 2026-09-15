from pathlib import Path

from backend.rag.parsers.text import TextDocumentParser


def test_text_parser_preserves_unicode_and_stable_identity(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("高斯过程\nPID tuning", encoding="utf-8")

    parser = TextDocumentParser()
    first = parser.parse(path)
    second = parser.parse(path)

    assert first.text == "高斯过程\nPID tuning"
    assert first.document.document_id == second.document.document_id
    assert len(first.document.content_hash) == 64
    assert first.document.source_kind == "text"


def test_text_parser_identity_survives_content_changes(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("first version", encoding="utf-8")
    parser = TextDocumentParser()
    first = parser.parse(path)
    path.write_text("second version", encoding="utf-8")

    second = parser.parse(path)

    assert second.document.document_id == first.document.document_id
    assert second.document.content_hash != first.document.content_hash


def test_markdown_parser_extracts_title_and_sections(tmp_path: Path) -> None:
    path = tmp_path / "paper.md"
    path.write_text(
        "# My Paper\nIntro text.\n## Methods\nPID text.\n## Results\nGood.",
        encoding="utf-8",
    )

    result = TextDocumentParser().parse(path)

    assert result.document.title == "My Paper"
    assert [section.heading for section in result.sections] == [
        "My Paper",
        "Methods",
        "Results",
    ]
    assert [section.level for section in result.sections] == [1, 2, 2]
    assert "PID text." in result.sections[1].text
    section = result.sections[1]
    assert result.text[section.start_char : section.end_char] == section.text
