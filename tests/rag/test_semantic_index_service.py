from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from backend.rag.chunking import CHUNKER_VERSION, StructureAwareChunker
from backend.rag.config import RagChunkingConfig, RagSemanticChunkingConfig
from backend.rag.index_manifest import IndexManifest, IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.models import (
    DocumentChunk,
    DocumentPage,
    DocumentSection,
    KnowledgeDocument,
    NormalizedDocument,
)
from backend.rag.semantic_chunking import (
    SEMANTIC_CHUNKER_VERSION,
    SemanticStructureAwareChunker,
)
from backend.rag.source_span import resolve_source_span


class SharedEmbedding:
    model_name = "shared-fake-qwen"
    dimension = 2

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.0, 1.0] if "TOPIC_B" in text else [1.0, 0.0] for text in texts]


class Store:
    def __init__(self) -> None:
        self.chunks: list[DocumentChunk] = []

    def upsert_chunks(self, chunks, vectors, *, generation_id=None) -> None:
        _ = generation_id
        assert len(chunks) == len(vectors)
        self.chunks = list(chunks)

    def list_chunks(self, *, generation_id=None):
        _ = generation_id
        return list(self.chunks)

    def delete_document(self, _document_id: str) -> None:
        self.chunks = []

    def delete_chunks(self, _chunk_ids: list[str]) -> None:
        return None

    def get_chunk(self, chunk_id: str):
        return next(
            (chunk for chunk in self.chunks if chunk.chunk_id == chunk_id), None
        )


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
    for chunk in store.chunks:
        assert chunk.source_span is not None
        assert (
            resolve_source_span(
                chunk.source_span,
                path.read_text(encoding="utf-8"),
                expected_document_hash=chunk.document_hash,
            )
            == chunk.text
        )
    record = manifest.get(first.document_id)
    assert record is not None
    assert record.chunker_version == service.chunker_version

    second = service.index_document(path)

    assert second.reused_existing is True
    assert len(embedding.calls) == 2


@pytest.mark.parametrize("invalid_mode", ["text", "page"])
def test_index_service_rejects_misaligned_evidence_before_replacing_ready_generation(
    tmp_path: Path,
    invalid_mode: str,
) -> None:
    path = tmp_path / "paper.txt"
    path.write_text(
        "Methods\n\nTOPIC_A first mechanism paragraph.\n\n"
        "TOPIC_A second mechanism paragraph.",
        encoding="utf-8",
    )
    embedding = SharedEmbedding()
    structural_chunker = StructureAwareChunker(
        RagChunkingConfig(
            target_tokens=80,
            preferred_max_tokens=90,
            hard_max_tokens=100,
            minimum_tokens=2,
            overlap_tokens=4,
        )
    )

    def parser_with_pages(path: str | Path) -> NormalizedDocument:
        document = parser(path)
        second_paragraph_start = document.text.index(
            "TOPIC_A second mechanism paragraph."
        )
        page_one_end = second_paragraph_start - 2
        return document.model_copy(
            update={
                "pages": [
                    DocumentPage(
                        page_number=1,
                        text=document.text[:page_one_end],
                        start_char=0,
                        end_char=page_one_end,
                    ),
                    DocumentPage(
                        page_number=2,
                        text=document.text[second_paragraph_start:],
                        start_char=second_paragraph_start,
                        end_char=len(document.text),
                    ),
                ]
            }
        )

    class SwitchingChunker:
        version = CHUNKER_VERSION

        def __init__(self) -> None:
            self.invalid_mode: str | None = None

        def chunk(self, document: NormalizedDocument) -> list[DocumentChunk]:
            chunks = structural_chunker.chunk(document)
            if self.invalid_mode == "text":
                chunks[0] = chunks[0].model_copy(
                    update={"text": "evidence that is not in the source"}
                )
            elif self.invalid_mode == "page":
                assert chunks[0].source_span is not None
                wrong_span = chunks[0].source_span.model_copy(
                    update={"page_start": 2, "page_end": 2}
                )
                metadata = {**chunks[0].metadata, "page_start": 2, "page_end": 2}
                chunks[0] = chunks[0].model_copy(
                    update={
                        "page_number": 2,
                        "metadata": metadata,
                        "source_span": wrong_span,
                    }
                )
            return chunks

    chunker = SwitchingChunker()
    manifest = IndexManifest(tmp_path / "manifest.json")
    store = Store()
    service = IndexService(
        chunker=chunker,
        embedding_provider=embedding,
        vector_store=store,
        manifest=manifest,
        parser=parser_with_pages,
    )

    initial = service.index_document(path)
    assert initial.status is IndexStatus.READY
    original_chunk_ids = [chunk.chunk_id for chunk in store.chunks]
    initial_embedding_call_count = len(embedding.calls)

    chunker.invalid_mode = invalid_mode
    rejected = service.reindex_document(path)

    assert rejected.status is IndexStatus.FAILED
    expected_error = (
        "does not match chunk evidence"
        if invalid_mode == "text"
        else "source page range does not match normalized document pages"
    )
    assert expected_error in rejected.error
    assert manifest.get(initial.document_id).status is IndexStatus.READY
    assert [chunk.chunk_id for chunk in store.chunks] == original_chunk_ids
    assert len(embedding.calls) == initial_embedding_call_count
