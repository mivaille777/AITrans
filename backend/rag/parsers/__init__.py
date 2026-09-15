from __future__ import annotations

from pathlib import Path

from backend.rag.config import RagAdvancedParsingConfig
from backend.rag.exceptions import UnsupportedDocumentTypeError
from backend.rag.models import NormalizedDocument
from backend.rag.multimodal import augment_document_with_visual_elements
from backend.rag.parsers.base import DocumentParser
from backend.rag.parsers.docling import (
    AdvancedParserWithFallback,
    DoclingDocumentParser,
)
from backend.rag.parsers.docx import DocxDocumentParser
from backend.rag.parsers.html import HtmlDocumentParser
from backend.rag.parsers.pdf import PdfDocumentParser
from backend.rag.parsers.text import TextDocumentParser

_DEFAULT_PARSERS: tuple[DocumentParser, ...] = (
    PdfDocumentParser(),
    DocxDocumentParser(),
    HtmlDocumentParser(),
    TextDocumentParser(),
)


def get_parser_for_path(
    source: str | Path,
    *,
    advanced_config: RagAdvancedParsingConfig | None = None,
) -> DocumentParser:
    for parser in _DEFAULT_PARSERS:
        if parser.supports(source):
            config = advanced_config or RagAdvancedParsingConfig()
            if config.enabled and DoclingDocumentParser.supported_suffixes.issuperset(
                {Path(source).suffix.lower()}
            ):
                return AdvancedParserWithFallback(
                    DoclingDocumentParser(config),
                    parser,
                )
            return parser
    suffix = Path(source).suffix.lower() or "<none>"
    raise UnsupportedDocumentTypeError(f"unsupported document type: {suffix}")


def parse_document(
    source: str | Path,
    *,
    advanced_config: RagAdvancedParsingConfig | None = None,
) -> NormalizedDocument:
    parsed = get_parser_for_path(source, advanced_config=advanced_config).parse(source)
    return augment_document_with_visual_elements(parsed, source)


__all__ = [
    "AdvancedParserWithFallback",
    "DoclingDocumentParser",
    "DocumentParser",
    "DocxDocumentParser",
    "HtmlDocumentParser",
    "PdfDocumentParser",
    "TextDocumentParser",
    "get_parser_for_path",
    "parse_document",
]
