from pathlib import Path

import pytest

from backend.rag.exceptions import RagParsingError
from backend.rag.parsers.pdf import PdfDocumentParser


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, _path: str) -> None:
        self.metadata = {"/Title": "Paper", "/Author": "Tester"}
        self.pages = [FakePage("Page one."), FakePage("第二页。")]


class EmptyReader:
    def __init__(self, _path: str) -> None:
        self.metadata: dict[str, str] = {}
        self.pages = [FakePage("")]


def test_pdf_parser_preserves_page_offsets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF fake")
    monkeypatch.setattr("backend.rag.parsers.pdf.PdfReader", FakeReader)

    result = PdfDocumentParser().parse(path)

    assert result.document.title == "Paper"
    assert result.document.metadata["author"] == "Tester"
    assert len(result.pages) == 2
    first_page, second_page = result.pages
    assert result.text[first_page.start_char : first_page.end_char] == "Page one."
    assert result.text[second_page.start_char : second_page.end_char] == "第二页。"
    assert result.metadata["page_count"] == 2
    assert result.metadata["parser_name"] == "pdf"
    assert result.metadata["parser_version"] == "pypdf-v1"
    assert result.metadata["layout_enabled"] is False
    assert result.metadata["table_enabled"] is False
    assert result.metadata["ocr_enabled"] is False
    assert result.metadata["image_understanding_enabled"] is False
    assert result.metadata["visual_content_mode"] == "text_layer_only"


def test_pdf_parser_reports_scanned_document_without_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF fake")
    monkeypatch.setattr("backend.rag.parsers.pdf.PdfReader", EmptyReader)

    with pytest.raises(RagParsingError, match="OCR is not enabled"):
        PdfDocumentParser().parse(path)
