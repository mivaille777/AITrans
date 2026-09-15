from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from backend.rag.config import RagAdvancedParsingConfig
from backend.rag.exceptions import RagParsingError
from backend.rag.models import DocumentPage, DocumentSection, NormalizedDocument
from backend.rag.parsers.base import (
    BaseFileParser,
    DocumentParser,
    ParsedBlock,
    compose_blocks,
)

_IMAGE_PLACEHOLDER = "<!-- image -->"


@dataclass(frozen=True, slots=True)
class DoclingConversion:
    """Text exported by Docling, optionally split by physical PDF page."""

    text: str = ""
    pages: tuple[tuple[int, str], ...] = ()


class DoclingBackend(Protocol):
    def convert(
        self,
        path: Path,
        config: RagAdvancedParsingConfig,
    ) -> str | DoclingConversion: ...


class DefaultDoclingBackend:
    """Lazy adapter that keeps Docling outside the normal installation path."""

    def convert(
        self,
        path: Path,
        config: RagAdvancedParsingConfig,
    ) -> DoclingConversion:
        try:
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise RagParsingError(
                "Docling is not installed; install the 'rag-advanced' optional "
                "dependency to enable advanced parsing"
            ) from exc

        def convert_path(input_path: Path):
            pipeline_options = PdfPipelineOptions(
                do_table_structure=config.table_enabled,
                do_ocr=config.ocr_enabled,
                do_formula_enrichment=config.formula_enabled,
                document_timeout=config.document_timeout_seconds,
                accelerator_options=AcceleratorOptions(device=config.device),
            )
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options,
                    )
                }
            )
            return converter.convert(input_path).document

        try:
            document = convert_path(path)
        except Exception as primary_error:
            # Some Docling/PDF-backend combinations on Windows reject an
            # otherwise valid source solely because its path contains Unicode
            # characters. Stage a byte-identical copy under an ASCII filename
            # before declaring the document unparsable.
            if path.as_posix().isascii():
                raise RagParsingError(
                    f"Docling failed to parse document: {path}"
                ) from primary_error
            try:
                with TemporaryDirectory(prefix="aitrans-docling-") as temporary:
                    staged_path = Path(temporary) / "document.pdf"
                    shutil.copy2(path, staged_path)
                    document = convert_path(staged_path)
            except Exception as staging_error:
                raise RagParsingError(
                    f"Docling failed to parse document: {path}"
                ) from staging_error

        try:
            if not config.layout_enabled:
                return DoclingConversion(text=str(document.export_to_text()))

            page_numbers = sorted(int(page_no) for page_no in document.pages)
            if page_numbers:
                page_markdown = tuple(
                    (
                        page_no,
                        str(
                            document.export_to_markdown(
                                page_no=page_no,
                                image_placeholder=_IMAGE_PLACEHOLDER,
                                traverse_pictures=True,
                            )
                        ),
                    )
                    for page_no in page_numbers
                )
                return DoclingConversion(pages=page_markdown)

            return DoclingConversion(
                text=str(
                    document.export_to_markdown(
                        image_placeholder=_IMAGE_PLACEHOLDER,
                        traverse_pictures=True,
                    )
                )
            )
        except Exception as exc:
            raise RagParsingError(f"Docling failed to parse document: {path}") from exc


def _markdown_blocks(text: str, *, layout_enabled: bool) -> list[ParsedBlock]:
    if not layout_enabled:
        return [ParsedBlock(text=text)]
    blocks: list[ParsedBlock] = []
    for raw_block in re.split(r"\n\s*\n", text):
        block = raw_block.replace(_IMAGE_PLACEHOLDER, "").strip()
        if not block:
            continue
        heading = re.fullmatch(r"(#{1,6})\s+(.+)", block)
        if heading:
            blocks.append(
                ParsedBlock(
                    text=heading.group(2).strip(),
                    heading_level=len(heading.group(1)),
                )
            )
        else:
            blocks.append(ParsedBlock(text=block))
    return blocks


def _compose_page_aware_blocks(
    pages: tuple[tuple[int, str], ...],
    *,
    layout_enabled: bool,
) -> tuple[str, list[DocumentSection], list[DocumentPage]]:
    """Compose canonical text while retaining both section and page offsets."""

    page_blocks: list[tuple[int, ParsedBlock]] = []
    ordered_page_numbers: list[int] = []
    for page_number, page_text in pages:
        if page_number not in ordered_page_numbers:
            ordered_page_numbers.append(page_number)
        normalized = BaseFileParser._normalize_text(page_text)
        for block in _markdown_blocks(normalized, layout_enabled=layout_enabled):
            if block.text.strip():
                page_blocks.append((page_number, block))

    if not page_blocks:
        return "", [], [
            DocumentPage(page_number=page_number)
            for page_number in ordered_page_numbers
        ]

    parts: list[str] = []
    positions: list[tuple[int, int]] = []
    cursor = 0
    for index, (_page_number, block) in enumerate(page_blocks):
        if index:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(block.text.strip())
        cursor += len(block.text.strip())
        positions.append((start, cursor))
    text = "".join(parts)

    document_pages: list[DocumentPage] = []
    previous_end = 0
    for page_number in ordered_page_numbers:
        indices = [
            index
            for index, (block_page, _block) in enumerate(page_blocks)
            if block_page == page_number
        ]
        if not indices:
            document_pages.append(
                DocumentPage(
                    page_number=page_number,
                    start_char=previous_end,
                    end_char=previous_end,
                )
            )
            continue
        start = positions[indices[0]][0]
        end = positions[indices[-1]][1]
        document_pages.append(
            DocumentPage(
                page_number=page_number,
                text=text[start:end],
                start_char=start,
                end_char=end,
            )
        )
        previous_end = end

    heading_indices = [
        index
        for index, (_page_number, block) in enumerate(page_blocks)
        if block.heading_level is not None
    ]
    sections: list[DocumentSection] = []
    for heading_position, block_index in enumerate(heading_indices):
        page_number, block = page_blocks[block_index]
        start = positions[block_index][0]
        if heading_position + 1 < len(heading_indices):
            next_start = positions[heading_indices[heading_position + 1]][0]
            end = len(text[:next_start].rstrip())
        else:
            end = len(text)
        sections.append(
            DocumentSection(
                heading=block.text.strip(),
                level=block.heading_level or 1,
                text=text[start:end],
                start_char=start,
                end_char=end,
                metadata={"page_number": page_number},
            )
        )
    return text, sections, document_pages


def _parser_profile_version(config: RagAdvancedParsingConfig) -> str:
    """Return an index-invalidating parser profile identifier."""

    return (
        "docling-v4"
        f";device={config.device}"
        f";layout={int(config.layout_enabled)}"
        f";table={int(config.table_enabled)}"
        f";ocr={int(config.ocr_enabled)}"
        f";formula={int(config.formula_enabled)}"
    )


class DoclingDocumentParser(BaseFileParser):
    name = "docling"
    version = "docling-v4"
    supported_suffixes = frozenset({".pdf"})

    def __init__(
        self,
        config: RagAdvancedParsingConfig | None = None,
        *,
        backend: DoclingBackend | None = None,
    ) -> None:
        self.config = config or RagAdvancedParsingConfig(enabled=True)
        self._backend = backend or DefaultDoclingBackend()

    def parse(self, source: str | Path) -> NormalizedDocument:
        path = self._resolve_source(source)
        raw_bytes = self._read_bytes(path)
        try:
            converted = self._backend.convert(path, self.config)
        except RagParsingError:
            raise
        except Exception as exc:
            raise RagParsingError(f"Docling failed to parse document: {path}") from exc

        pages: list[DocumentPage] = []
        if isinstance(converted, DoclingConversion) and converted.pages:
            text, sections, pages = _compose_page_aware_blocks(
                converted.pages,
                layout_enabled=self.config.layout_enabled,
            )
        else:
            raw_text = converted.text if isinstance(converted, DoclingConversion) else converted
            normalized = self._normalize_text(raw_text)
            text, sections = compose_blocks(
                _markdown_blocks(normalized, layout_enabled=self.config.layout_enabled)
            )
        if not text.strip():
            raise RagParsingError(f"Docling produced no extractable text: {path}")

        title = sections[0].heading if sections else path.stem
        try:
            library_version = version("docling")
        except PackageNotFoundError:
            library_version = "injected-backend"
        parser_version = _parser_profile_version(self.config)
        document = self._build_document(
            path=path,
            raw_bytes=raw_bytes,
            title=title,
            source_kind="pdf",
            mime_type="application/pdf",
            metadata={
                "advanced_parser": True,
                "parser_name": self.name,
                "parser_version": parser_version,
                "parser_device": self.config.device,
                "layout_preserved": self.config.layout_enabled,
                "table_structure_enabled": self.config.table_enabled,
                "ocr_enabled": self.config.ocr_enabled,
                "formula_enrichment_enabled": self.config.formula_enabled,
                "figure_caption_preserved": self.config.layout_enabled,
                "image_understanding_enabled": False,
                "visual_content_mode": "caption_and_text_only",
            },
        )
        return NormalizedDocument(
            document=document,
            text=text,
            sections=sections,
            pages=pages,
            metadata={
                "parser_name": self.name,
                "parser_version": parser_version,
                "parser_device": self.config.device,
                "library_version": library_version,
                "layout_enabled": self.config.layout_enabled,
                "table_enabled": self.config.table_enabled,
                "ocr_enabled": self.config.ocr_enabled,
                "formula_enabled": self.config.formula_enabled,
                "section_count": len(sections),
                "page_count": len(pages),
                "figure_caption_preserved": self.config.layout_enabled,
                "image_understanding_enabled": False,
                "visual_content_mode": "caption_and_text_only",
            },
        )


class AdvancedParserWithFallback:
    name = "advanced_with_basic_fallback"
    version = "1"

    def __init__(self, primary: DocumentParser, fallback: DocumentParser) -> None:
        self.primary = primary
        self.fallback = fallback
        self.supported_suffixes = primary.supported_suffixes.intersection(
            fallback.supported_suffixes
        )

    def supports(self, source: str | Path) -> bool:
        return self.primary.supports(source) and self.fallback.supports(source)

    def parse(self, source: str | Path) -> NormalizedDocument:
        try:
            return self.primary.parse(source)
        except RagParsingError as exc:
            result = self.fallback.parse(source)
            return result.model_copy(
                update={
                    "metadata": {
                        **result.metadata,
                        "advanced_parser_enabled": True,
                        "advanced_parser_fallback": True,
                        "advanced_parser_name": self.primary.name,
                        "advanced_parser_error": str(exc)[:300],
                    }
                }
            )


__all__ = [
    "AdvancedParserWithFallback",
    "DefaultDoclingBackend",
    "DoclingBackend",
    "DoclingConversion",
    "DoclingDocumentParser",
]
