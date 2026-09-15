from pathlib import Path

import pytest

from backend.rag.exceptions import UnsupportedDocumentTypeError
from backend.rag.parsers import (
    DocxDocumentParser,
    HtmlDocumentParser,
    PdfDocumentParser,
    TextDocumentParser,
    get_parser_for_path,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("paper.pdf", PdfDocumentParser),
        ("paper.docx", DocxDocumentParser),
        ("notes.md", TextDocumentParser),
        ("notes.txt", TextDocumentParser),
        ("page.html", HtmlDocumentParser),
    ],
)
def test_registry_selects_parser(name: str, expected: type[object]) -> None:
    assert isinstance(get_parser_for_path(Path(name)), expected)


def test_registry_rejects_unsupported_type() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        get_parser_for_path("data.csv")
