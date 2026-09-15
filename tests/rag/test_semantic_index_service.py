from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagChunkingConfig, RagSemanticChunkingConfig
from backend.rag.index_manifest import IndexManifest, IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.models import (
    DocumentChunk,
    DocumentSection,
    KnowledgeDocument,
    NormalizedDocument,
)
from backend.rag.semantic_chunking import (
    SEMANTIC_CHUNKER_VERSION,
    SemanticStructureAwareChunker,
)


class SharedEmbedding:
    model_name = "shared-fake-qwen"
    dimension = 2

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [
            [0.0, 1.0] if "TOPIC_B" in text else [1.0, 0.0]
            for text in texts
        ]


class Store:
    def __init__(self) -> None:
        self.chunks: list[DocumentChunk] = []

    def upsert_chunks(self, chunks, vectors) -> None:
        assert len(chunks) == len(vectors)
        self.chunks = list(chunks)

    def delete_document(self, _document_id: str) -> None:
        self.chunks = []

    def delete_chunks(self, _chunk_ids: list[str]) -> None:
        return None

    def get_chunk(self, chunk_id: str):
        return next((chunk for chunk in self.chunks if chunk.chunk_id == chunk_id), None)


def parser(path: str | Path) -> NormalizedDocument:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    digest = sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id="parser-id",
            title="Semantic Paper",
            source_uri=source.resolve().as_uri(),
            source_kind="text",
            mime_type="text/plain",
            language="en",
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
        metadata={"parser_version": "semantic-parser-v1"},
    )


def test_index_service_reuses_one_embedding_provider_for_semantics_and_final_chunks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.txt"
    path.write_text(
        "Methods\n\n"
        "TOPIC_A first mechanism paragraph.\n\n"
        "TOPIC_A second mechanism paragraph.\n\n"
        "TOPIC_B different refinement paragraph.",
        encoding="utf-8",
    )
    embedding = SharedEmbedding()
    chunker = SemanticStructureAwareChunker(
        base_chunker=StructureAwareChunker(
            RagChunkingConfig(
                target_tokens=80,
                preferred_max_tokens=90,
                hard_max_tokens=100,
                overlap_tokens=4,
                minimum_tokens=2,
            )
        ),
        semantic_config=RagSemanticChunkingConfig(
            enabled=True,
            adaptive_threshold_enabled=False,
        ),
        embedding_provider=embedding,
    )
    manifest = IndexManifest(tmp_path / "manifest.json")
    store = Store()
    service = IndexService(
        chunker=chunker,
        embedding_provider=embedding,
        vector_store=store,
        manifest=manifest,
        parser=parser,
    )

    first = service.index_document(path)

    assert first.status is IndexStatus.READY
    assert service.chunker_version.startswith(SEMANTIC_CHUNKER_VERSION)
    assert len(embedding.calls) == 2
    assert all("Paragraph:" in item for item in embedding.calls[0])
    assert embedding.calls[1] == [chunk.text for chunk in store.chunks]
    assert len(store.chunks) == 2
    record = manifest.get(first.document_id)
    assert record is not None
    assert record.chunker_version == service.chunker_version

    second = service.index_document(path)

    assert second.reused_existing is True
    assert len(embedding.calls) == 2
