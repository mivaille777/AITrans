from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256

from backend.rag.models import DocumentPage, DocumentSection, NormalizedDocument

_BLOCK_PARAGRAPH = "paragraph"
_BLOCK_HEADING = "heading"
_BLOCK_TABLE = "table"
_BLOCK_TABLE_CAPTION = "table_caption"
_BLOCK_FIGURE_CAPTION = "figure_caption"
_BLOCK_EQUATION = "equation"
_BLOCK_REFERENCE_ENTRY = "reference_entry"

_HEADING_PREFIX = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*)|(?:[ivxlcdm]+)|(?:[a-z]))[\s.():\-]+",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_REFERENCE_ENTRY_START = re.compile(
    r"(?m)^\s*(?:\[\d+\]|\(\d+\)|\d+[.)])\s+"
)
_TABLE_CAPTION = re.compile(r"^\s*(table|表)\s*[.:]?\s*\d+\b", re.IGNORECASE)
_FIGURE_CAPTION = re.compile(
    r"^\s*(fig(?:ure)?\.?|图)\s*[.:]?\s*\d+\b",
    re.IGNORECASE,
)
_EQUATION_LABEL = re.compile(
    r"^\s*(?:eq(?:uation)?\.?\s*\(?\d+\)?|式\s*\(?\d+\)?)",
    re.IGNORECASE,
)
_DISPLAY_EQUATION = re.compile(
    r"(?:\$\$.+?\$\$|\\\[.+?\\\]|\\begin\{(?:equation|align|aligned|gather)\*?\})",
    re.IGNORECASE | re.DOTALL,
)
_MARKDOWN_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)

_REFERENCE_HEADINGS = {
    "references",
    "reference",
    "bibliography",
    "works cited",
    "reference list",
    "参考文献",
    "引用文献",
}


@dataclass(frozen=True, slots=True)
class DocumentParagraphNode:
    """Atomic source block retained with semantic type and exact provenance."""

    node_id: str
    paragraph_index: int
    start_char: int
    end_char: int
    text: str
    block_type: str = _BLOCK_PARAGRAPH
    label: str = ""
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True, slots=True)
class DocumentSectionNode:
    """A section/subsection in document order with its hierarchy path."""

    node_id: str
    heading: str
    level: int
    section_path: tuple[str, ...]
    parent_section_id: str | None
    start_char: int
    end_char: int
    paragraphs: tuple[DocumentParagraphNode, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    synthetic: bool = False


@dataclass(frozen=True, slots=True)
class DocumentTree:
    document_id: str
    sections: tuple[DocumentSectionNode, ...]


class DocumentTreeBuilder:
    """Build a hierarchy-first representation from normalized parser offsets.

    Parser sections remain non-overlapping source regions. The tree adds the
    conceptual parent/child relationship by heading level. Paragraph-like
    source blocks are classified before chunking so tables, captions, equations,
    and reference entries can use dedicated chunking strategies.
    """

    @classmethod
    def build(cls, document: NormalizedDocument) -> DocumentTree:
        text = document.text
        if not text:
            return DocumentTree(document_id=document.document.document_id, sections=())

        valid_sections = cls._valid_sections(text, document.sections)
        regions = cls._regions(text, valid_sections)
        paragraph_index = 0
        section_nodes: list[DocumentSectionNode] = []
        hierarchy_stack: list[DocumentSectionNode] = []

        for region_index, (start, end, section) in enumerate(regions):
            if start >= end:
                continue
            heading = section.heading.strip() if section is not None else ""
            level = section.level if section is not None else 0
            synthetic = section is None

            if synthetic:
                parent_section_id = None
                section_path: tuple[str, ...] = ()
                hierarchy_stack.clear()
            else:
                while hierarchy_stack and hierarchy_stack[-1].level >= level:
                    hierarchy_stack.pop()
                parent = hierarchy_stack[-1] if hierarchy_stack else None
                parent_section_id = parent.node_id if parent else None
                section_path = (*parent.section_path, heading) if parent else (heading,)

            node_id = cls._section_id(
                document.document.document_id,
                region_index,
                start,
                heading,
            )
            reference_section = cls._is_reference_section(heading)
            raw_spans = cls._block_spans(
                text,
                start,
                end,
                reference_section=reference_section,
                heading=heading,
            )
            paragraphs: list[DocumentParagraphNode] = []
            for paragraph_start, paragraph_end in raw_spans:
                block_text = text[paragraph_start:paragraph_end]
                page_start, page_end = cls._page_range(
                    paragraph_start,
                    paragraph_end,
                    document.pages,
                )
                block_type, label = cls._classify_block(
                    block_text,
                    heading=heading,
                    reference_section=reference_section,
                )
                paragraphs.append(
                    DocumentParagraphNode(
                        node_id=f"{node_id}:p{paragraph_index}",
                        paragraph_index=paragraph_index,
                        start_char=paragraph_start,
                        end_char=paragraph_end,
                        text=block_text,
                        block_type=block_type,
                        label=label,
                        page_start=page_start,
                        page_end=page_end,
                    )
                )
                paragraph_index += 1

            node = DocumentSectionNode(
                node_id=node_id,
                heading=heading,
                level=level,
                section_path=section_path,
                parent_section_id=parent_section_id,
                start_char=start,
                end_char=end,
                paragraphs=tuple(paragraphs),
                metadata={
                    **(dict(section.metadata) if section is not None else {}),
                    "reference_section": reference_section,
                },
                synthetic=synthetic,
            )
            section_nodes.append(node)
            if not synthetic:
                hierarchy_stack.append(node)

        return DocumentTree(
            document_id=document.document.document_id,
            sections=tuple(section_nodes),
        )

    @classmethod
    def _block_spans(
        cls,
        text: str,
        start: int,
        end: int,
        *,
        reference_section: bool,
        heading: str,
    ) -> list[tuple[int, int]]:
        paragraphs = cls._paragraph_spans(text, start, end)
        if not reference_section:
            return paragraphs

        refined: list[tuple[int, int]] = []
        for paragraph_start, paragraph_end in paragraphs:
            block_text = text[paragraph_start:paragraph_end]
            if cls._is_heading_text(block_text, heading):
                refined.append((paragraph_start, paragraph_end))
                continue
            entries = cls._reference_entry_spans(text, paragraph_start, paragraph_end)
            if entries:
                refined.extend(entries)
            else:
                refined.append((paragraph_start, paragraph_end))
        return refined

    @staticmethod
    def _reference_entry_spans(
        text: str,
        start: int,
        end: int,
    ) -> list[tuple[int, int]]:
        block = text[start:end]
        matches = list(_REFERENCE_ENTRY_START.finditer(block))
        if len(matches) < 2:
            return []
        spans: list[tuple[int, int]] = []
        for index, match in enumerate(matches):
            entry_start = start + match.start()
            entry_end = (
                start + matches[index + 1].start()
                if index + 1 < len(matches)
                else end
            )
            left, right = DocumentTreeBuilder._trim_span(text, entry_start, entry_end)
            if left < right:
                spans.append((left, right))
        return spans

    @classmethod
    def _classify_block(
        cls,
        block_text: str,
        *,
        heading: str,
        reference_section: bool,
    ) -> tuple[str, str]:
        stripped = block_text.strip()
        if cls._is_heading_text(stripped, heading):
            return _BLOCK_HEADING, heading.strip()
        if reference_section:
            return _BLOCK_REFERENCE_ENTRY, cls._reference_label(stripped)
        if cls._is_markdown_table(stripped):
            return _BLOCK_TABLE, "table"
        table_caption = _TABLE_CAPTION.match(stripped)
        if table_caption:
            return _BLOCK_TABLE_CAPTION, cls._leading_label(stripped)
        figure_caption = _FIGURE_CAPTION.match(stripped)
        if figure_caption:
            return _BLOCK_FIGURE_CAPTION, cls._leading_label(stripped)
        if _EQUATION_LABEL.match(stripped) or _DISPLAY_EQUATION.search(stripped):
            return _BLOCK_EQUATION, cls._equation_label(stripped)
        return _BLOCK_PARAGRAPH, ""

    @staticmethod
    def _is_markdown_table(value: str) -> bool:
        lines = [line for line in value.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        if not all("|" in line for line in lines[: min(len(lines), 4)]):
            return False
        return any(_MARKDOWN_TABLE_SEPARATOR.match(line) for line in lines[1:3])

    @classmethod
    def _is_reference_section(cls, heading: str) -> bool:
        return cls._normalize_heading(heading) in _REFERENCE_HEADINGS

    @staticmethod
    def _normalize_heading(value: str) -> str:
        normalized = _HEADING_PREFIX.sub("", str(value or "").strip().casefold())
        return _NON_WORD.sub(" ", normalized).strip()

    @staticmethod
    def _is_heading_text(value: str, heading: str) -> bool:
        return bool(heading.strip()) and value.strip() == heading.strip()

    @staticmethod
    def _leading_label(value: str) -> str:
        first_line = value.splitlines()[0].strip()
        match = re.match(
            r"^(?:table|fig(?:ure)?\.?|表|图)\s*[.:]?\s*\d+",
            first_line,
            flags=re.IGNORECASE,
        )
        return match.group(0).strip() if match else first_line[:80]

    @staticmethod
    def _equation_label(value: str) -> str:
        first_line = value.splitlines()[0].strip()
        match = _EQUATION_LABEL.match(first_line)
        return match.group(0).strip() if match else "equation"

    @staticmethod
    def _reference_label(value: str) -> str:
        match = _REFERENCE_ENTRY_START.match(value)
        return match.group(0).strip() if match else "reference"

    @staticmethod
    def _valid_sections(
        text: str,
        sections: list[DocumentSection],
    ) -> list[DocumentSection]:
        return sorted(
            (
                section
                for section in sections
                if section.start_char < section.end_char
                and section.start_char < len(text)
                and section.end_char > 0
            ),
            key=lambda section: (section.start_char, section.end_char),
        )

    @staticmethod
    def _regions(
        text: str,
        sections: list[DocumentSection],
    ) -> list[tuple[int, int, DocumentSection | None]]:
        if not sections:
            return [(0, len(text), None)]

        regions: list[tuple[int, int, DocumentSection | None]] = []
        cursor = 0
        for section in sections:
            start = max(cursor, section.start_char, 0)
            end = min(max(start, section.end_char), len(text))
            if cursor < start:
                regions.append((cursor, start, None))
            if start < end:
                regions.append((start, end, section))
                cursor = end
        if cursor < len(text):
            regions.append((cursor, len(text), None))
        return regions

    @staticmethod
    def _paragraph_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        cursor = start
        index = start
        while index < end:
            if text[index] == "\n":
                boundary_start = index
                probe = index
                newline_count = 0
                while probe < end:
                    if text[probe] == "\n":
                        newline_count += 1
                        probe += 1
                        continue
                    if text[probe] in " \t\r":
                        probe += 1
                        continue
                    break
                if newline_count >= 2:
                    left, right = DocumentTreeBuilder._trim_span(text, cursor, boundary_start)
                    if left < right:
                        spans.append((left, right))
                    cursor = probe
                    index = probe
                    continue
            index += 1

        left, right = DocumentTreeBuilder._trim_span(text, cursor, end)
        if left < right:
            spans.append((left, right))
        return spans

    @staticmethod
    def _page_range(
        start: int,
        end: int,
        pages: list[DocumentPage],
    ) -> tuple[int | None, int | None]:
        intersecting = sorted(
            (page for page in pages if start < page.end_char and end > page.start_char),
            key=lambda page: page.page_number,
        )
        if not intersecting:
            return None, None
        return intersecting[0].page_number, intersecting[-1].page_number

    @staticmethod
    def _section_id(
        document_id: str,
        index: int,
        start_char: int,
        heading: str,
    ) -> str:
        digest = sha256(
            f"{document_id}\x1f{index}\x1f{start_char}\x1f{heading}".encode("utf-8")
        ).hexdigest()[:16]
        return f"section_{digest}"

    @staticmethod
    def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return start, end


__all__ = [
    "DocumentParagraphNode",
    "DocumentSectionNode",
    "DocumentTree",
    "DocumentTreeBuilder",
]
