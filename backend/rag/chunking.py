from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass

from backend.rag.config import RagChunkingConfig
from backend.rag.document_tree import (
    DocumentParagraphNode,
    DocumentSectionNode,
    DocumentTreeBuilder,
)
from backend.rag.exceptions import RagInvariantError
from backend.rag.models import (
    DocumentChunk,
    DocumentPage,
    NormalizedDocument,
    build_stable_chunk_id,
)
from backend.rag.tokenization import HeuristicTokenCounter, TokenCounter

CHUNKER_VERSION = "hierarchical-special-block-v3"

_SENTENCE_BREAK = re.compile(r"(?:[.!?。！？；;]+[\"'”’）)】》]*)(?=\s|$)|\n+")

_BLOCK_PARAGRAPH = "paragraph"
_BLOCK_HEADING = "heading"
_BLOCK_TABLE = "table"
_BLOCK_TABLE_CAPTION = "table_caption"
_BLOCK_FIGURE_CAPTION = "figure_caption"
_BLOCK_EQUATION = "equation"
_BLOCK_REFERENCE_ENTRY = "reference_entry"


@dataclass(frozen=True, slots=True)
class _ChunkSpan:
    start: int
    end: int
    section: DocumentSectionNode
    paragraph_start_index: int | None
    paragraph_end_index: int | None
    boundary_strategy: str
    chunk_type: str = "paragraph_group"
    special_labels: tuple[str, ...] = ()
    block_types: tuple[str, ...] = ()


class StructureAwareChunker:
    """Hierarchy-first chunker for academic and structured documents.

    Section/subsection and paragraph boundaries define normal prose chunks.
    Tables, figure captions, equations, and bibliography entries are handled as
    dedicated semantic blocks. Token counts are soft/preferred/hard bounds and
    sentence overlap is only used when one semantic block exceeds the hard limit.
    """

    def __init__(
        self,
        config: RagChunkingConfig | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._config = config or RagChunkingConfig()
        self._token_counter = token_counter or HeuristicTokenCounter()

    @property
    def config(self) -> RagChunkingConfig:
        return self._config

    @property
    def token_counter(self) -> TokenCounter:
        return self._token_counter

    def chunk(self, document: NormalizedDocument) -> list[DocumentChunk]:
        text = document.text
        if not text or not text.strip():
            return []
        if not document.document.content_hash:
            raise RagInvariantError(
                "normalized document content_hash must not be empty"
            )

        tree = DocumentTreeBuilder.build(document)
        spans: list[_ChunkSpan] = []
        for section in tree.sections:
            spans.extend(self._chunk_section(text, section))

        chunks: list[DocumentChunk] = []
        for chunk_index, span in enumerate(spans):
            chunk_text = text[span.start : span.end]
            pages = self._intersecting_pages(span.start, span.end, document.pages)
            page_number = pages[0].page_number if pages else None
            metadata = self._build_metadata(document, span, pages, chunk_text)
            chunks.append(
                DocumentChunk(
                    chunk_id=build_stable_chunk_id(
                        document_hash=document.document.content_hash,
                        section_heading=span.section.heading,
                        chunk_index=chunk_index,
                        text=chunk_text,
                    ),
                    document_id=document.document.document_id,
                    text=chunk_text,
                    title=document.document.title,
                    section_heading=span.section.heading,
                    section_path=list(span.section.section_path),
                    hierarchy_level=span.section.level,
                    parent_section_id=span.section.parent_section_id or "",
                    chunk_type=span.chunk_type,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    paragraph_index=span.paragraph_start_index,
                    paragraph_end_index=span.paragraph_end_index,
                    start_char=span.start,
                    end_char=span.end,
                    token_count=self._token_counter.count(chunk_text),
                    language=document.document.language,
                    source_uri=document.document.source_uri,
                    document_hash=document.document.content_hash,
                    parser_version=str(document.metadata.get("parser_version", "")),
                    chunker_version=CHUNKER_VERSION,
                    metadata=metadata,
                )
            )
        return chunks

    def _chunk_section(
        self,
        text: str,
        section: DocumentSectionNode,
    ) -> list[_ChunkSpan]:
        paragraphs = list(section.paragraphs)
        if not paragraphs:
            return []
        if bool(section.metadata.get("reference_section")):
            return self._chunk_reference_section(text, section, paragraphs)

        spans: list[_ChunkSpan] = []
        buffer: list[DocumentParagraphNode] = []
        index = 0
        while index < len(paragraphs):
            paragraph = paragraphs[index]

            if paragraph.block_type == _BLOCK_TABLE_CAPTION and self._next_is(
                paragraphs, index, _BLOCK_TABLE
            ):
                table = paragraphs[index + 1]
                lead = self._lead_heading(buffer)
                start = lead.start_char if lead else paragraph.start_char
                self._flush_nonlead_buffer(spans, section, buffer)
                buffer = []
                spans.append(
                    self._special_span(
                        section,
                        start=start,
                        end=table.end_char,
                        first=lead or paragraph,
                        last=table,
                        chunk_type="table",
                        boundary_strategy="table_block",
                        labels=(paragraph.label, table.label),
                        block_types=tuple(
                            block.block_type
                            for block in (lead, paragraph, table)
                            if block is not None
                        ),
                    )
                )
                index += 2
                continue

            if paragraph.block_type == _BLOCK_TABLE:
                end = paragraph.end_char
                labels = [paragraph.label]
                block_types = [paragraph.block_type]
                last = paragraph
                consumed = 1
                if self._next_is(paragraphs, index, _BLOCK_TABLE_CAPTION):
                    caption = paragraphs[index + 1]
                    end = caption.end_char
                    labels.append(caption.label)
                    block_types.append(caption.block_type)
                    last = caption
                    consumed = 2
                lead = self._lead_heading(buffer)
                start = lead.start_char if lead else paragraph.start_char
                self._flush_nonlead_buffer(spans, section, buffer)
                buffer = []
                spans.append(
                    self._special_span(
                        section,
                        start=start,
                        end=end,
                        first=lead or paragraph,
                        last=last,
                        chunk_type="table",
                        boundary_strategy="table_block",
                        labels=tuple(labels),
                        block_types=tuple(
                            ([lead.block_type] if lead else []) + block_types
                        ),
                    )
                )
                index += consumed
                continue

            if paragraph.block_type == _BLOCK_FIGURE_CAPTION:
                lead = self._lead_heading(buffer)
                start = lead.start_char if lead else paragraph.start_char
                self._flush_nonlead_buffer(spans, section, buffer)
                buffer = []
                end = paragraph.end_char
                last = paragraph
                consumed = 1
                if self._next_is(paragraphs, index, _BLOCK_PARAGRAPH):
                    context = paragraphs[index + 1]
                    if (
                        self._token_counter.count(text[start : context.end_char])
                        <= self._config.effective_hard_max_tokens
                    ):
                        end = context.end_char
                        last = context
                        consumed = 2
                spans.append(
                    self._special_span(
                        section,
                        start=start,
                        end=end,
                        first=lead or paragraph,
                        last=last,
                        chunk_type="figure_context",
                        boundary_strategy="figure_context",
                        labels=(paragraph.label,),
                        block_types=tuple(
                            block.block_type
                            for block in (lead, paragraph, last)
                            if block is not None
                        ),
                    )
                )
                index += consumed
                continue

            if paragraph.block_type == _BLOCK_EQUATION:
                context_before: DocumentParagraphNode | None = None
                if buffer and buffer[-1].block_type == _BLOCK_PARAGRAPH:
                    context_before = buffer.pop()
                lead = self._lead_heading(buffer)
                if lead is not None:
                    buffer = []
                else:
                    self._flush_buffer(spans, section, buffer)
                    buffer = []
                first = lead or context_before or paragraph
                start = first.start_char
                end = paragraph.end_char
                last = paragraph
                consumed = 1
                if self._next_is(paragraphs, index, _BLOCK_PARAGRAPH):
                    context_after = paragraphs[index + 1]
                    if (
                        self._token_counter.count(text[start : context_after.end_char])
                        <= self._config.effective_hard_max_tokens
                    ):
                        end = context_after.end_char
                        last = context_after
                        consumed = 2
                spans.append(
                    self._special_span(
                        section,
                        start=start,
                        end=end,
                        first=first,
                        last=last,
                        chunk_type="equation_context",
                        boundary_strategy="equation_context",
                        labels=(paragraph.label,),
                        block_types=tuple(
                            block.block_type
                            for block in (lead, context_before, paragraph, last)
                            if block is not None
                        ),
                    )
                )
                index += consumed
                continue

            paragraph_tokens = self._token_counter.count(paragraph.text)
            if paragraph_tokens > self._config.effective_hard_max_tokens:
                if buffer and (
                    self._lead_heading(buffer) is not None
                    or self._buffer_tokens(text, buffer) <= self._config.minimum_tokens
                ):
                    start = buffer[0].start_char
                    paragraph_start_index = buffer[0].paragraph_index
                    block_types = tuple(item.block_type for item in buffer)
                    buffer = []
                    spans.extend(
                        self._split_oversized_range(
                            text,
                            section,
                            start=start,
                            end=paragraph.end_char,
                            paragraph_start_index=paragraph_start_index,
                            paragraph_end_index=paragraph.paragraph_index,
                            chunk_type="paragraph_group",
                            block_types=(*block_types, paragraph.block_type),
                        )
                    )
                else:
                    self._flush_buffer(spans, section, buffer)
                    buffer = []
                    spans.extend(
                        self._split_oversized_range(
                            text,
                            section,
                            start=paragraph.start_char,
                            end=paragraph.end_char,
                            paragraph_start_index=paragraph.paragraph_index,
                            paragraph_end_index=paragraph.paragraph_index,
                            chunk_type="paragraph_group",
                            block_types=(paragraph.block_type,),
                        )
                    )
                index += 1
                continue

            if not buffer:
                buffer.append(paragraph)
                index += 1
                continue

            combined_tokens = self._token_counter.count(
                text[buffer[0].start_char : paragraph.end_char]
            )
            if (
                self._lead_heading(buffer) is not None
                and combined_tokens <= self._config.effective_hard_max_tokens
            ):
                buffer.append(paragraph)
                index += 1
                continue

            current_tokens = self._buffer_tokens(text, buffer)
            if self._should_keep_paragraph_group(
                current_tokens=current_tokens,
                combined_tokens=combined_tokens,
            ):
                buffer.append(paragraph)
            else:
                self._flush_buffer(spans, section, buffer)
                buffer = [paragraph]
            index += 1

        self._flush_buffer(spans, section, buffer)
        return spans

    def _chunk_reference_section(
        self,
        text: str,
        section: DocumentSectionNode,
        paragraphs: list[DocumentParagraphNode],
    ) -> list[_ChunkSpan]:
        spans: list[_ChunkSpan] = []
        buffer: list[DocumentParagraphNode] = []
        hard = self._config.effective_hard_max_tokens
        preferred = self._config.effective_preferred_max_tokens

        for paragraph in paragraphs:
            paragraph_tokens = self._token_counter.count(paragraph.text)
            if paragraph_tokens > hard:
                self._flush_reference_buffer(spans, section, buffer)
                buffer = []
                spans.extend(
                    self._split_oversized_range(
                        text,
                        section,
                        start=paragraph.start_char,
                        end=paragraph.end_char,
                        paragraph_start_index=paragraph.paragraph_index,
                        paragraph_end_index=paragraph.paragraph_index,
                        chunk_type="reference_group",
                        special_labels=(paragraph.label,),
                        block_types=(paragraph.block_type,),
                        boundary_strategy="reference_entry_fallback",
                    )
                )
                continue

            if not buffer:
                buffer.append(paragraph)
                continue

            combined_tokens = self._token_counter.count(
                text[buffer[0].start_char : paragraph.end_char]
            )
            current_tokens = self._buffer_tokens(text, buffer)
            if combined_tokens <= hard and (
                current_tokens < self._config.target_tokens or combined_tokens <= preferred
            ):
                buffer.append(paragraph)
                continue

            self._flush_reference_buffer(spans, section, buffer)
            buffer = [paragraph]

        self._flush_reference_buffer(spans, section, buffer)
        return spans

    def _should_keep_paragraph_group(
        self,
        *,
        current_tokens: int,
        combined_tokens: int,
    ) -> bool:
        preferred = self._config.effective_preferred_max_tokens
        hard = self._config.effective_hard_max_tokens
        if combined_tokens > hard:
            return False
        if current_tokens < self._config.target_tokens and combined_tokens <= preferred:
            return True
        return current_tokens <= self._config.minimum_tokens and combined_tokens <= hard

    def _split_oversized_range(
        self,
        text: str,
        section: DocumentSectionNode,
        *,
        start: int,
        end: int,
        paragraph_start_index: int,
        paragraph_end_index: int,
        chunk_type: str,
        special_labels: tuple[str, ...] = (),
        block_types: tuple[str, ...] = (),
        boundary_strategy: str = "sentence_fallback",
    ) -> list[_ChunkSpan]:
        start, end = self._trim_span(text, start, end)
        spans: list[_ChunkSpan] = []
        cursor = start
        while cursor < end:
            chunk_end = self._choose_fallback_end(text, cursor, end)
            chunk_start, chunk_end = self._trim_span(text, cursor, chunk_end)
            if chunk_start >= chunk_end:
                break
            spans.append(
                _ChunkSpan(
                    start=chunk_start,
                    end=chunk_end,
                    section=section,
                    paragraph_start_index=paragraph_start_index,
                    paragraph_end_index=paragraph_end_index,
                    boundary_strategy=boundary_strategy,
                    chunk_type=chunk_type,
                    special_labels=special_labels,
                    block_types=block_types,
                )
            )
            if chunk_end >= end:
                break
            next_start = self._fallback_overlap_start(text, chunk_start, chunk_end)
            next_start, _ = self._trim_span(text, next_start, end)
            if next_start <= chunk_start:
                next_start = chunk_end
            cursor = next_start
        return spans

    def _choose_fallback_end(self, text: str, start: int, end: int) -> int:
        hard = self._config.effective_hard_max_tokens
        preferred = self._config.effective_preferred_max_tokens
        if self._token_counter.count(text[start:end]) <= hard:
            return end

        hard_end = self._largest_prefix_end(text, start, end, hard)
        preferred_end = self._largest_prefix_end(
            text,
            start,
            hard_end,
            min(preferred, hard),
        )
        sentence_boundaries = [
            match.end()
            for match in _SENTENCE_BREAK.finditer(text, start, hard_end)
            if start < match.end() <= hard_end
            and self._token_counter.count(text[start : match.end()])
            > self._config.minimum_tokens
        ]
        before_preferred = [
            boundary for boundary in sentence_boundaries if boundary <= preferred_end
        ]
        if before_preferred:
            return before_preferred[-1]
        after_preferred = [
            boundary for boundary in sentence_boundaries if boundary > preferred_end
        ]
        if after_preferred:
            return after_preferred[0]
        return self._prefer_word_boundary(text, start, hard_end)

    def _fallback_overlap_start(self, text: str, chunk_start: int, chunk_end: int) -> int:
        if self._config.overlap_tokens == 0:
            return chunk_end

        low = chunk_start
        high = chunk_end
        while low < high:
            middle = (low + high) // 2
            if self._token_counter.count(text[middle:chunk_end]) <= self._config.overlap_tokens:
                high = middle
            else:
                low = middle + 1
        overlap_start = low

        sentence_starts = [
            match.end()
            for match in _SENTENCE_BREAK.finditer(text, overlap_start, chunk_end)
            if match.end() < chunk_end
        ]
        if sentence_starts:
            return sentence_starts[0]
        return self._advance_to_token_boundary(text, overlap_start, chunk_end)

    def _buffer_tokens(
        self,
        text: str,
        buffer: list[DocumentParagraphNode],
    ) -> int:
        if not buffer:
            return 0
        return self._token_counter.count(text[buffer[0].start_char : buffer[-1].end_char])

    @staticmethod
    def _next_is(
        paragraphs: list[DocumentParagraphNode],
        index: int,
        block_type: str,
    ) -> bool:
        return index + 1 < len(paragraphs) and paragraphs[index + 1].block_type == block_type

    @staticmethod
    def _lead_heading(
        buffer: list[DocumentParagraphNode],
    ) -> DocumentParagraphNode | None:
        if len(buffer) == 1 and buffer[0].block_type == _BLOCK_HEADING:
            return buffer[0]
        return None

    def _flush_nonlead_buffer(
        self,
        spans: list[_ChunkSpan],
        section: DocumentSectionNode,
        buffer: list[DocumentParagraphNode],
    ) -> None:
        if self._lead_heading(buffer) is not None:
            return
        self._flush_buffer(spans, section, buffer)

    @staticmethod
    def _special_span(
        section: DocumentSectionNode,
        *,
        start: int,
        end: int,
        first: DocumentParagraphNode,
        last: DocumentParagraphNode,
        chunk_type: str,
        boundary_strategy: str,
        labels: tuple[str, ...],
        block_types: tuple[str, ...],
    ) -> _ChunkSpan:
        return _ChunkSpan(
            start=start,
            end=end,
            section=section,
            paragraph_start_index=first.paragraph_index,
            paragraph_end_index=last.paragraph_index,
            boundary_strategy=boundary_strategy,
            chunk_type=chunk_type,
            special_labels=tuple(label for label in labels if label),
            block_types=tuple(dict.fromkeys(block_types)),
        )

    @staticmethod
    def _flush_buffer(
        spans: list[_ChunkSpan],
        section: DocumentSectionNode,
        buffer: list[DocumentParagraphNode],
    ) -> None:
        if not buffer:
            return
        spans.append(
            _ChunkSpan(
                start=buffer[0].start_char,
                end=buffer[-1].end_char,
                section=section,
                paragraph_start_index=buffer[0].paragraph_index,
                paragraph_end_index=buffer[-1].paragraph_index,
                boundary_strategy="paragraph_group",
                chunk_type="paragraph_group",
                special_labels=tuple(item.label for item in buffer if item.label),
                block_types=tuple(dict.fromkeys(item.block_type for item in buffer)),
            )
        )

    @staticmethod
    def _flush_reference_buffer(
        spans: list[_ChunkSpan],
        section: DocumentSectionNode,
        buffer: list[DocumentParagraphNode],
    ) -> None:
        if not buffer:
            return
        entries = [item for item in buffer if item.block_type == _BLOCK_REFERENCE_ENTRY]
        spans.append(
            _ChunkSpan(
                start=buffer[0].start_char,
                end=buffer[-1].end_char,
                section=section,
                paragraph_start_index=buffer[0].paragraph_index,
                paragraph_end_index=buffer[-1].paragraph_index,
                boundary_strategy="reference_group",
                chunk_type="reference_group",
                special_labels=tuple(item.label for item in entries if item.label),
                block_types=tuple(dict.fromkeys(item.block_type for item in buffer)),
            )
        )

    def _largest_prefix_end(
        self,
        text: str,
        start: int,
        limit: int,
        token_limit: int,
    ) -> int:
        low = start + 1
        high = limit
        best = start
        while low <= high:
            middle = (low + high) // 2
            if self._token_counter.count(text[start:middle]) <= token_limit:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return max(best, min(start + 1, limit))

    @staticmethod
    def _prefer_word_boundary(text: str, start: int, end: int) -> int:
        candidate = end
        while candidate > start and not text[candidate - 1].isspace():
            candidate -= 1
        return candidate if candidate > start else end

    @staticmethod
    def _advance_to_token_boundary(text: str, start: int, end: int) -> int:
        if start <= 0 or start >= end:
            return start
        if not (
            StructureAwareChunker._is_latin_word_char(text[start - 1])
            and StructureAwareChunker._is_latin_word_char(text[start])
        ):
            return start
        while start < end and StructureAwareChunker._is_latin_word_char(text[start]):
            start += 1
        return start

    @staticmethod
    def _is_latin_word_char(character: str) -> bool:
        return character.isascii() and (character.isalnum() or character in "_-'’")

    @staticmethod
    def _intersecting_pages(
        start: int,
        end: int,
        pages: list[DocumentPage],
    ) -> list[DocumentPage]:
        return sorted(
            (page for page in pages if start < page.end_char and end > page.start_char),
            key=lambda page: page.page_number,
        )

    def _build_metadata(
        self,
        document: NormalizedDocument,
        span: _ChunkSpan,
        pages: list[DocumentPage],
        chunk_text: str,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "source_kind": document.document.source_kind,
            "mime_type": document.document.mime_type,
            "boundary_strategy": span.boundary_strategy,
            "section_path": list(span.section.section_path),
            "hierarchy_level": span.section.level,
            "parent_section_id": span.section.parent_section_id or "",
            "paragraph_start": span.paragraph_start_index,
            "paragraph_end": span.paragraph_end_index,
            "chunk_type": span.chunk_type,
            "block_types": list(span.block_types),
            "special_labels": list(span.special_labels),
            "section_kind": (
                "references"
                if bool(span.section.metadata.get("reference_section"))
                else "content"
            ),
        }
        if span.chunk_type == "reference_group":
            metadata["reference_entry_count"] = len(span.special_labels)
        if span.chunk_type in {"table", "figure_context", "equation_context"}:
            metadata["special_block"] = True
        if (
            span.chunk_type != "paragraph_group"
            and self._token_counter.count(chunk_text)
            > self._config.effective_hard_max_tokens
        ):
            metadata["oversized_special_block"] = True
        if document.document.metadata:
            metadata["document_metadata"] = deepcopy(document.document.metadata)
        if document.metadata:
            metadata["normalized_document_metadata"] = deepcopy(document.metadata)
        if span.section.metadata:
            metadata["section_metadata"] = deepcopy(span.section.metadata)
        if pages:
            metadata["page_start"] = pages[0].page_number
            metadata["page_end"] = pages[-1].page_number
        return metadata

    @staticmethod
    def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return start, end


def chunk_document(
    document: NormalizedDocument,
    *,
    config: RagChunkingConfig | None = None,
    token_counter: TokenCounter | None = None,
) -> list[DocumentChunk]:
    return StructureAwareChunker(config=config, token_counter=token_counter).chunk(document)


__all__ = ["CHUNKER_VERSION", "StructureAwareChunker", "chunk_document"]
