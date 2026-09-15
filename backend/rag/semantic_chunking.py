from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from statistics import fmean, pstdev

from backend.rag.chunking import CHUNKER_VERSION as STRUCTURAL_CHUNKER_VERSION
from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagSemanticChunkingConfig
from backend.rag.document_tree import (
    DocumentParagraphNode,
    DocumentSectionNode,
    DocumentTreeBuilder,
)
from backend.rag.embeddings.base import EmbeddingProvider
from backend.rag.models import (
    DocumentChunk,
    DocumentPage,
    NormalizedDocument,
    build_stable_chunk_id,
)
from backend.rag.tokenization import HeuristicTokenCounter, TokenCounter

SEMANTIC_CHUNKER_VERSION = "hierarchical-semantic-v4"

_BLOCK_HEADING = "heading"
_BLOCK_PARAGRAPH = "paragraph"
_REPLACEABLE_BOUNDARY = "paragraph_group"


@dataclass(frozen=True, slots=True)
class _SemanticGroup:
    nodes: tuple[DocumentParagraphNode, ...]
    paragraph_nodes: tuple[DocumentParagraphNode, ...]
    cohesion: float
    break_before: float | None
    break_after: float | None
    boundary_reason: str
    adaptive_threshold: float | None


class SemanticStructureAwareChunker:
    """Add paragraph-level semantic boundaries on top of structural chunking.

    The structural chunker remains authoritative for hard section boundaries,
    special academic blocks, and oversized sentence fallback. This layer only
    replaces ordinary ``paragraph_group`` chunks with groups decided from
    paragraph embeddings inside the same leaf section.
    """

    def __init__(
        self,
        *,
        base_chunker: StructureAwareChunker,
        semantic_config: RagSemanticChunkingConfig,
        embedding_provider: EmbeddingProvider,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._base = base_chunker
        self._semantic = semantic_config
        self._embedding = embedding_provider
        self._token_counter = token_counter or base_chunker.token_counter or HeuristicTokenCounter()

    @property
    def version(self) -> str:
        return (
            SEMANTIC_CHUNKER_VERSION
            if self._semantic.enabled
            else STRUCTURAL_CHUNKER_VERSION
        )

    @property
    def config(self):
        return self._base.config

    def chunk(self, document: NormalizedDocument) -> list[DocumentChunk]:
        base_chunks = self._base.chunk(document)
        if not self._semantic.enabled or not base_chunks:
            return base_chunks

        try:
            chunks = self._semantic_rechunk(document, base_chunks)
        except Exception as exc:  # noqa: BLE001 - semantic grouping is additive
            reason = str(exc) or exc.__class__.__name__
            return [
                self._with_version(
                    chunk,
                    metadata_updates={
                        "semantic_chunking_enabled": True,
                        "semantic_chunking_applied": False,
                        "semantic_chunking_fallback_reason": reason,
                    },
                )
                for chunk in base_chunks
            ]
        return [self._with_version(chunk) for chunk in chunks]

    def _semantic_rechunk(
        self,
        document: NormalizedDocument,
        base_chunks: list[DocumentChunk],
    ) -> list[DocumentChunk]:
        tree = DocumentTreeBuilder.build(document)
        replaceable = [
            chunk
            for chunk in base_chunks
            if chunk.chunk_type == "paragraph_group"
            and str(chunk.metadata.get("boundary_strategy", ""))
            == _REPLACEABLE_BOUNDARY
        ]
        if not replaceable:
            return base_chunks

        replaced_ids: set[str] = set()
        semantic_chunks: list[DocumentChunk] = []
        for section in tree.sections:
            section_chunks = [
                chunk
                for chunk in replaceable
                if chunk.section_path == list(section.section_path)
                and chunk.start_char < section.end_char
                and chunk.end_char > section.start_char
            ]
            if not section_chunks:
                continue

            eligible = [
                node
                for node in section.paragraphs
                if node.block_type in {_BLOCK_HEADING, _BLOCK_PARAGRAPH}
                and self._covered_by_simple_prose(node, section_chunks)
            ]
            paragraph_nodes = [
                node for node in eligible if node.block_type == _BLOCK_PARAGRAPH
            ]
            if not paragraph_nodes:
                continue

            vectors = self._embed_section_paragraphs(document, section, paragraph_nodes)
            vector_by_id = {
                node.node_id: vector
                for node, vector in zip(paragraph_nodes, vectors, strict=True)
            }
            segments = self._contiguous_segments(eligible)
            section_group_index = 0
            for segment in segments:
                if not any(node.block_type == _BLOCK_PARAGRAPH for node in segment):
                    continue
                groups = self._group_segment(
                    document,
                    section,
                    segment,
                    vector_by_id,
                )
                for group in groups:
                    semantic_chunks.append(
                        self._build_chunk(
                            document,
                            section,
                            group,
                            section_group_index=section_group_index,
                            template_chunks=section_chunks,
                        )
                    )
                    section_group_index += 1
                    group_start = group.nodes[0].start_char
                    group_end = group.nodes[-1].end_char
                    for chunk in section_chunks:
                        if chunk.start_char < group_end and chunk.end_char > group_start:
                            replaced_ids.add(chunk.chunk_id)

        if not semantic_chunks:
            return base_chunks

        retained = [chunk for chunk in base_chunks if chunk.chunk_id not in replaced_ids]
        ordered = sorted(
            [*retained, *semantic_chunks],
            key=lambda chunk: (
                chunk.start_char,
                chunk.end_char,
                chunk.chunk_type,
                chunk.chunk_id,
            ),
        )
        finalized: list[DocumentChunk] = []
        for chunk_index, chunk in enumerate(ordered):
            finalized.append(
                chunk.model_copy(
                    update={
                        "chunk_id": build_stable_chunk_id(
                            document_hash=document.document.content_hash,
                            section_heading=chunk.section_heading,
                            chunk_index=chunk_index,
                            text=chunk.text,
                        ),
                        "chunk_index": chunk_index,
                    }
                )
            )
        return finalized

    def _embed_section_paragraphs(
        self,
        document: NormalizedDocument,
        section: DocumentSectionNode,
        paragraphs: list[DocumentParagraphNode],
    ) -> list[list[float]]:
        section_context = " > ".join(section.section_path).strip()
        texts = [
            (
                f"Section: {section_context}\n\nParagraph:\n{paragraph.text.strip()}"
                if section_context
                else paragraph.text.strip()
            )
            for paragraph in paragraphs
        ]
        vectors = self._embedding.embed_documents(texts)
        if len(vectors) != len(paragraphs):
            raise ValueError(
                "semantic paragraph embedding count mismatch: "
                f"expected {len(paragraphs)}, got {len(vectors)}"
            )
        return vectors

    def _group_segment(
        self,
        document: NormalizedDocument,
        section: DocumentSectionNode,
        nodes: list[DocumentParagraphNode],
        vectors: dict[str, list[float]],
    ) -> list[_SemanticGroup]:
        prose = [node for node in nodes if node.block_type == _BLOCK_PARAGRAPH]
        if not prose:
            return []
        adaptive = self._adaptive_threshold(prose, vectors)
        boundary_scores = {
            (left.node_id, right.node_id): self._cosine(
                vectors[left.node_id], vectors[right.node_id]
            )
            for left, right in zip(prose, prose[1:])
        }

        leading_heading = nodes[0] if nodes[0].block_type == _BLOCK_HEADING else None
        first = prose[0]
        buffer: list[DocumentParagraphNode] = [first]
        group_nodes: list[DocumentParagraphNode] = (
            [leading_heading, first] if leading_heading is not None else [first]
        )
        groups_raw: list[tuple[list[DocumentParagraphNode], list[DocumentParagraphNode], float | None, str]] = []
        break_before: float | None = None
        boundary_reason = "section_start"

        for paragraph in prose[1:]:
            similarity = self._cosine(
                vectors[paragraph.node_id],
                self._centroid(
                    [
                        vectors[item.node_id]
                        for item in buffer[-self._semantic.centroid_window :]
                    ]
                ),
            )
            start_char = group_nodes[0].start_char
            current_end = group_nodes[-1].end_char
            current_tokens = self._token_counter.count(
                document.text[start_char:current_end]
            )
            combined_tokens = self._token_counter.count(
                document.text[start_char:paragraph.end_char]
            )
            should_merge, split_reason = self._merge_decision(
                similarity=similarity,
                adaptive_threshold=adaptive,
                current_tokens=current_tokens,
                combined_tokens=combined_tokens,
            )
            if should_merge:
                buffer.append(paragraph)
                group_nodes.append(paragraph)
                continue

            groups_raw.append(
                (list(group_nodes), list(buffer), break_before, boundary_reason)
            )
            buffer = [paragraph]
            group_nodes = [paragraph]
            break_before = similarity
            boundary_reason = split_reason

        groups_raw.append((list(group_nodes), list(buffer), break_before, boundary_reason))

        groups: list[_SemanticGroup] = []
        for index, (all_nodes, paragraph_nodes, before, reason) in enumerate(groups_raw):
            after: float | None = None
            if index + 1 < len(groups_raw):
                next_paragraphs = groups_raw[index + 1][1]
                if paragraph_nodes and next_paragraphs:
                    after = boundary_scores.get(
                        (paragraph_nodes[-1].node_id, next_paragraphs[0].node_id)
                    )
            groups.append(
                _SemanticGroup(
                    nodes=tuple(all_nodes),
                    paragraph_nodes=tuple(paragraph_nodes),
                    cohesion=self._cohesion(paragraph_nodes, vectors),
                    break_before=before,
                    break_after=after,
                    boundary_reason=reason,
                    adaptive_threshold=adaptive,
                )
            )
        return groups

    def _merge_decision(
        self,
        *,
        similarity: float,
        adaptive_threshold: float | None,
        current_tokens: int,
        combined_tokens: int,
    ) -> tuple[bool, str]:
        preferred = self._base.config.effective_preferred_max_tokens
        hard = self._base.config.effective_hard_max_tokens
        minimum = self._base.config.minimum_tokens

        if combined_tokens > hard:
            return False, "token_hard_limit"
        if similarity < self._semantic.strong_split_similarity:
            return False, "strong_semantic_split"
        if (
            adaptive_threshold is not None
            and similarity < adaptive_threshold
            and current_tokens >= minimum
        ):
            return False, "adaptive_semantic_split"

        if combined_tokens <= preferred:
            threshold = (
                self._semantic.small_chunk_merge_similarity
                if current_tokens <= minimum
                else self._semantic.merge_similarity
            )
            if similarity >= threshold:
                return True, "semantic_merge"
            return False, "semantic_threshold"

        if similarity >= self._semantic.strong_merge_similarity:
            return True, "strong_semantic_merge"
        return False, "token_preferred_limit"

    def _adaptive_threshold(
        self,
        paragraphs: list[DocumentParagraphNode],
        vectors: dict[str, list[float]],
    ) -> float | None:
        if (
            not self._semantic.adaptive_threshold_enabled
            or len(paragraphs) < self._semantic.min_paragraphs_for_adaptive
        ):
            return None
        similarities = [
            self._cosine(vectors[left.node_id], vectors[right.node_id])
            for left, right in zip(paragraphs, paragraphs[1:])
        ]
        if not similarities:
            return None
        mean = fmean(similarities)
        deviation = pstdev(similarities) if len(similarities) > 1 else 0.0
        threshold = mean - self._semantic.adaptive_std_factor * deviation
        return max(
            self._semantic.strong_split_similarity,
            min(self._semantic.merge_similarity, threshold),
        )

    def _build_chunk(
        self,
        document: NormalizedDocument,
        section: DocumentSectionNode,
        group: _SemanticGroup,
        *,
        section_group_index: int,
        template_chunks: list[DocumentChunk],
    ) -> DocumentChunk:
        start = group.nodes[0].start_char
        end = group.nodes[-1].end_char
        text = document.text[start:end]
        pages = self._intersecting_pages(start, end, document.pages)
        page_number = pages[0].page_number if pages else None
        template = next(
            (
                chunk
                for chunk in template_chunks
                if chunk.start_char < end and chunk.end_char > start
            ),
            template_chunks[0],
        )
        metadata = deepcopy(template.metadata)
        metadata.update(
            {
                "boundary_strategy": "semantic_paragraph_group",
                "semantic_chunking_enabled": True,
                "semantic_chunking_applied": True,
                "semantic_embedding_model": self._embedding.model_name,
                "semantic_group_id": self._semantic_group_id(
                    document.document.content_hash,
                    section.node_id,
                    section_group_index,
                    start,
                    end,
                ),
                "semantic_group_index": section_group_index,
                "semantic_cohesion": round(group.cohesion, 6),
                "semantic_break_before": self._rounded(group.break_before),
                "semantic_break_after": self._rounded(group.break_after),
                "semantic_boundary_reason": group.boundary_reason,
                "semantic_adaptive_threshold": self._rounded(
                    group.adaptive_threshold
                ),
                "paragraph_start": group.paragraph_nodes[0].paragraph_index,
                "paragraph_end": group.paragraph_nodes[-1].paragraph_index,
                "block_types": list(
                    dict.fromkeys(node.block_type for node in group.nodes)
                ),
            }
        )
        if pages:
            metadata["page_start"] = pages[0].page_number
            metadata["page_end"] = pages[-1].page_number

        return DocumentChunk(
            chunk_id=f"semantic_pending_{section.node_id}_{section_group_index}",
            document_id=document.document.document_id,
            text=text,
            title=document.document.title,
            section_heading=section.heading,
            section_path=list(section.section_path),
            hierarchy_level=section.level,
            parent_section_id=section.parent_section_id or "",
            chunk_type="paragraph_group",
            page_number=page_number,
            chunk_index=0,
            paragraph_index=group.paragraph_nodes[0].paragraph_index,
            paragraph_end_index=group.paragraph_nodes[-1].paragraph_index,
            start_char=start,
            end_char=end,
            token_count=self._token_counter.count(text),
            language=document.document.language,
            source_uri=document.document.source_uri,
            document_hash=document.document.content_hash,
            parser_version=str(document.metadata.get("parser_version", "")),
            chunker_version=self.version,
            metadata=metadata,
        )

    def _cohesion(
        self,
        paragraphs: list[DocumentParagraphNode],
        vectors: dict[str, list[float]],
    ) -> float:
        group_vectors = [vectors[item.node_id] for item in paragraphs]
        if len(group_vectors) <= 1:
            return 1.0
        centroid = self._centroid(group_vectors)
        return fmean(self._cosine(vector, centroid) for vector in group_vectors)

    @staticmethod
    def _covered_by_simple_prose(
        node: DocumentParagraphNode,
        chunks: list[DocumentChunk],
    ) -> bool:
        return any(
            chunk.start_char <= node.start_char and chunk.end_char >= node.end_char
            for chunk in chunks
        )

    @staticmethod
    def _contiguous_segments(
        nodes: list[DocumentParagraphNode],
    ) -> list[list[DocumentParagraphNode]]:
        segments: list[list[DocumentParagraphNode]] = []
        current: list[DocumentParagraphNode] = []
        for node in nodes:
            if current and node.paragraph_index != current[-1].paragraph_index + 1:
                segments.append(current)
                current = []
            current.append(node)
        if current:
            segments.append(current)
        return segments

    @staticmethod
    def _centroid(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            raise ValueError("cannot compute centroid for empty vectors")
        dimension = len(vectors[0])
        if dimension == 0 or any(len(vector) != dimension for vector in vectors):
            raise ValueError("semantic embedding dimensions are inconsistent")
        return [fmean(vector[index] for vector in vectors) for index in range(dimension)]

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("semantic embedding dimensions are inconsistent")
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        value = numerator / (left_norm * right_norm)
        return max(-1.0, min(1.0, value))

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

    @staticmethod
    def _semantic_group_id(
        document_hash: str,
        section_id: str,
        group_index: int,
        start: int,
        end: int,
    ) -> str:
        digest = sha256(
            f"{document_hash}\x1f{section_id}\x1f{group_index}\x1f{start}\x1f{end}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        return f"semantic_{digest}"

    @staticmethod
    def _rounded(value: float | None) -> float | None:
        return round(value, 6) if value is not None else None

    def _with_version(
        self,
        chunk: DocumentChunk,
        *,
        metadata_updates: dict[str, object] | None = None,
    ) -> DocumentChunk:
        metadata = deepcopy(chunk.metadata)
        if metadata_updates:
            metadata.update(metadata_updates)
        return chunk.model_copy(
            update={
                "chunker_version": self.version,
                "metadata": metadata,
            }
        )


__all__ = ["SEMANTIC_CHUNKER_VERSION", "SemanticStructureAwareChunker"]
