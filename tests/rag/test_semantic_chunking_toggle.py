from __future__ import annotations

from hashlib import sha256

from backend.rag.chunking import CHUNKER_VERSION, StructureAwareChunker
from backend.rag.config import RagChunkingConfig, RagSemanticChunkingConfig
from backend.rag.models import DocumentSection, KnowledgeDocument, NormalizedDocument
from backend.rag.semantic_chunking import SemanticStructureAwareChunker


class NoCallEmbedding:
    model_name = "unused"
    dimension = 2

    def embed_query(self, _text: str) -> list[float]:
        raise AssertionError("semantic embedding must stay disabled")

    def embed_documents(self, _texts: list[str]) -> list[list[float]]:
        raise AssertionError("semantic embedding must stay disabled")


def test_disabled_semantic_layer_is_exact_structural_baseline() -> None:
    text = "Methods\n\nFirst paragraph.\n\nSecond paragraph."
    digest = sha256(text.encode("utf-8")).hexdigest()
    document = NormalizedDocument(
        document=KnowledgeDocument(
            document_id="doc-toggle",
            title="Toggle Paper",
            content_hash=digest,
        ),
        text=text,
        sections=[
            DocumentSection(
                heading="Methods",
                level=1,
                text=text,
                start_char=0,
                end_char=len(text),
            )
        ],
        metadata={"parser_version": "test"},
    )
    base = StructureAwareChunker(
        RagChunkingConfig(
            target_tokens=20,
            preferred_max_tokens=24,
            hard_max_tokens=30,
            overlap_tokens=4,
            minimum_tokens=2,
        )
    )
    baseline = base.chunk(document)
    wrapper = SemanticStructureAwareChunker(
        base_chunker=base,
        semantic_config=RagSemanticChunkingConfig(enabled=False),
        embedding_provider=NoCallEmbedding(),
    )

    actual = wrapper.chunk(document)

    assert wrapper.version == CHUNKER_VERSION
    assert actual == baseline
