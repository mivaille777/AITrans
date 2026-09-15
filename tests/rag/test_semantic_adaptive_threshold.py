from __future__ import annotations

from hashlib import sha256

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagChunkingConfig, RagSemanticChunkingConfig
from backend.rag.models import DocumentSection, KnowledgeDocument, NormalizedDocument
from backend.rag.semantic_chunking import SemanticStructureAwareChunker


class AdaptiveEmbedding:
    dimension = 2
    model_name = "adaptive-fake"

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if "SHIFT" in text:
                vectors.append([0.6, 0.8])
            else:
                vectors.append([1.0, 0.0])
        return vectors


def test_adaptive_threshold_detects_local_drop_above_absolute_split_floor() -> None:
    text = (
        "Discussion\n\n"
        "BASE first argument.\n\n"
        "BASE second argument.\n\n"
        "BASE third argument.\n\n"
        "SHIFT mechanism transition.\n\n"
        "SHIFT follow-up explanation."
    )
    digest = sha256(text.encode("utf-8")).hexdigest()
    document = NormalizedDocument(
        document=KnowledgeDocument(
            document_id="doc-adaptive",
            title="Adaptive Paper",
            content_hash=digest,
            language="en",
        ),
        text=text,
        sections=[
            DocumentSection(
                heading="Discussion",
                level=1,
                text=text,
                start_char=0,
                end_char=len(text),
            )
        ],
        metadata={"parser_version": "test"},
    )
    chunker = SemanticStructureAwareChunker(
        base_chunker=StructureAwareChunker(
            RagChunkingConfig(
                target_tokens=100,
                preferred_max_tokens=110,
                hard_max_tokens=120,
                overlap_tokens=4,
                minimum_tokens=2,
            )
        ),
        semantic_config=RagSemanticChunkingConfig(
            enabled=True,
            merge_similarity=0.72,
            strong_merge_similarity=0.82,
            strong_split_similarity=0.58,
            small_chunk_merge_similarity=0.78,
            adaptive_threshold_enabled=True,
            adaptive_std_factor=1.0,
            min_paragraphs_for_adaptive=4,
            centroid_window=4,
        ),
        embedding_provider=AdaptiveEmbedding(),
    )

    chunks = chunker.chunk(document)

    assert len(chunks) == 2
    assert chunks[1].metadata["semantic_boundary_reason"] == "adaptive_semantic_split"
    threshold = chunks[1].metadata["semantic_adaptive_threshold"]
    boundary = chunks[1].metadata["semantic_break_before"]
    assert threshold is not None
    assert boundary is not None
    assert boundary > 0.58
    assert boundary < threshold
