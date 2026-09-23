from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import quote

from backend.rag.benchmarks.qasper.schema import QasperPaper
from backend.rag.models import (
    DocumentSection,
    KnowledgeDocument,
    NormalizedDocument,
)


@dataclass(frozen=True, slots=True)
class QasperParagraphSpan:
    paragraph_id: str
    global_index: int
    section_name: str
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class QasperAdaptedPaper:
    document: NormalizedDocument
    paragraphs: tuple[QasperParagraphSpan, ...]


def adapt_qasper_paper(paper: QasperPaper, *, split: str) -> QasperAdaptedPaper:
    """Convert one structured QASPER paper without involving a PDF parser."""

    parts: list[str] = []
    sections: list[DocumentSection] = []
    paragraph_spans: list[QasperParagraphSpan] = []
    cursor = 0
    for source_section in paper.sections:
        section_paragraphs = [
            paragraph for paragraph in source_section.paragraphs if paragraph.text.strip()
        ]
        if not section_paragraphs:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        section_start = cursor
        for paragraph_index, paragraph in enumerate(section_paragraphs):
            if paragraph_index:
                parts.append("\n\n")
                cursor += 2
            start_char = cursor
            parts.append(paragraph.text)
            cursor += len(paragraph.text)
            paragraph_spans.append(
                QasperParagraphSpan(
                    paragraph_id=paragraph.paragraph_id,
                    global_index=paragraph.global_index,
                    section_name=source_section.name,
                    text=paragraph.text,
                    start_char=start_char,
                    end_char=cursor,
                )
            )
        sections.append(
            DocumentSection(
                heading=source_section.name,
                level=1,
                text="".join(parts)[section_start:cursor],
                start_char=section_start,
                end_char=cursor,
                metadata={"qasper_section_index": source_section.section_index},
            )
        )
    text = "".join(parts)
    if not text.strip():
        raise ValueError(f"QASPER paper {paper.paper_id!r} has no indexable paragraphs")
    document_id = f"qasper:{split}:{paper.paper_id}"
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    document = KnowledgeDocument(
        document_id=document_id,
        title=paper.title or paper.paper_id,
        source_uri=f"qasper://{quote(split, safe='')}/{quote(paper.paper_id, safe='')}",
        source_kind="qasper",
        mime_type="application/json",
        language="en",
        content_hash=content_hash,
        metadata={
            "dataset": "qasper",
            "dataset_version": "0.3",
            "split": split,
            "paper_id": paper.paper_id,
        },
    )
    normalized = NormalizedDocument(
        document=document,
        text=text,
        sections=sections,
        metadata={
            "dataset": "qasper",
            "dataset_version": "0.3",
            "split": split,
            "paper_id": paper.paper_id,
            "parser_name": "qasper-structured-adapter",
            "parser_version": "qasper-v0.3",
            "paragraph_ids": [item.paragraph_id for item in paragraph_spans],
        },
    )
    return QasperAdaptedPaper(document=normalized, paragraphs=tuple(paragraph_spans))


__all__ = ["QasperAdaptedPaper", "QasperParagraphSpan", "adapt_qasper_paper"]
