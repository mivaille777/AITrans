from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, __version__ as pypdf_version

from backend.rag.exceptions import RagParsingError
from backend.rag.models import DocumentPage, NormalizedDocument
from backend.rag.parsers.base import BaseFileParser


class PdfDocumentParser(BaseFileParser):
    name = "pdf"
    version = "pypdf-v1"
    supported_suffixes = frozenset({".pdf"})

    def parse(self, source: str | Path) -> NormalizedDocument:
        path = self._resolve_source(source)
        raw_bytes = self._read_bytes(path)
        try:
            reader = PdfReader(str(path))
            metadata = reader.metadata or {}
            page_texts = [
                self._normalize_text(page.extract_text() or "") for page in reader.pages
            ]
        except Exception as exc:
            raise RagParsingError(f"failed to parse PDF document: {path}") from exc

        parts: list[str] = []
        pages: list[DocumentPage] = []
        cursor = 0
        for page_number, page_text in enumerate(page_texts, start=1):
            if parts:
                parts.append("\n\n")
                cursor += 2
            start = cursor
            parts.append(page_text)
            cursor += len(page_text)
            pages.append(
                DocumentPage(
                    page_number=page_number,
                    text=page_text,
                    start_char=start,
                    end_char=cursor,
                )
            )
        text = "".join(parts)
        if not text.strip():
            raise RagParsingError(
                f"PDF contains no extractable text; OCR is not enabled in the basic parser: {path}"
            )

        pdf_metadata: dict[str, object] = {}
        metadata_map = {
            "author": "/Author",
            "subject": "/Subject",
            "creator": "/Creator",
        }
        for key, pdf_key in metadata_map.items():
            value = metadata.get(pdf_key) if hasattr(metadata, "get") else None
            if value:
                pdf_metadata[key] = str(value)
        title_value = metadata.get("/Title") if hasattr(metadata, "get") else None
        pdf_metadata.update(
            {
                "parser_name": self.name,
                "parser_version": self.version,
                "layout_preserved": False,
                "table_structure_enabled": False,
                "ocr_enabled": False,
                "formula_enrichment_enabled": False,
                "image_understanding_enabled": False,
                "visual_content_mode": "text_layer_only",
            }
        )

        document = self._build_document(
            path=path,
            raw_bytes=raw_bytes,
            title=str(title_value or path.stem),
            source_kind="pdf",
            mime_type="application/pdf",
            metadata=pdf_metadata,
        )
        return NormalizedDocument(
            document=document,
            text=text,
            pages=pages,
            metadata={
                "parser_name": self.name,
                "parser_version": self.version,
                "library_version": pypdf_version,
                "page_count": len(pages),
                "layout_enabled": False,
                "table_enabled": False,
                "ocr_enabled": False,
                "formula_enabled": False,
                "image_understanding_enabled": False,
                "visual_content_mode": "text_layer_only",
            },
        )


__all__ = ["PdfDocumentParser"]
