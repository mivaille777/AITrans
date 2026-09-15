from __future__ import annotations

import base64
from pathlib import Path

from backend.rag.config import RagVisualUnderstandingConfig
from backend.rag.evidence_builder import build_evidence_item
from backend.rag.index_manifest import IndexManifest, IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.models import (
    DocumentChunk,
    DocumentElement,
    KnowledgeDocument,
    NormalizedDocument,
    RetrievalCandidate,
)
from backend.rag.multimodal import build_multimodal_chunks
from backend.rag.vision import (
    OpenAICompatibleVisualDescriptionProvider,
    enrich_document_with_visual_descriptions,
    visual_description_index_version,
)

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
)


class FakeVisualProvider:
    name = "fake_vlm"
    model_name = "fake-vision-model"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[Path] = []

    def describe(
        self,
        *,
        image_path: Path,
        title: str,
        caption: str,
        page_number: int | None,
        section_path,
    ) -> str:
        self.calls.append(image_path)
        if self.fail:
            raise RuntimeError("synthetic VLM failure")
        return (
            "A block diagram shows an input passing through a controller "
            "to a plant with a feedback connection."
        )

    def close(self) -> None:
        return None


class FakeCompletionClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete_messages(self, **kwargs):
        self.calls.append(kwargs)
        return "A line chart compares two controller responses over time."


def _config(**updates) -> RagVisualUnderstandingConfig:
    values = {
        "enabled": True,
        "provider": "openai_compatible",
        "model": "vision-model",
        "base_url": "http://127.0.0.1:8000/v1",
        "inherit_ai_settings": False,
    }
    values.update(updates)
    return RagVisualUnderstandingConfig(**values)


def _document(tmp_path: Path, *, content_hash: str = "hash-v1") -> NormalizedDocument:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF mock")
    image = tmp_path / "figure.png"
    image.write_bytes(_TINY_PNG)
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id="doc-test",
            title="Control paper",
            source_uri=source.as_uri(),
            source_kind="pdf",
            mime_type="application/pdf",
            content_hash=content_hash,
        ),
        text="Text evidence.",
        elements=[
            DocumentElement(
                element_id="element-1",
                document_id="doc-test",
                modality="picture",
                surrogate_text="Figure. Fig. 1. Closed-loop architecture. Page: 2.",
                page_number=2,
                section_path=["Method"],
                caption="Fig. 1. Closed-loop architecture.",
                asset_uri=image.as_uri(),
                metadata={"extraction_backend": "test"},
            )
        ],
        metadata={
            "parser_version": "fake-parser-v1",
            "visual_content_mode": "surrogate_text_and_asset",
        },
    )


def test_visual_description_enriches_retrieval_text_and_evidence(tmp_path: Path) -> None:
    provider = FakeVisualProvider()
    enriched = enrich_document_with_visual_descriptions(
        _document(tmp_path),
        config=_config(),
        provider=provider,
    )

    assert len(provider.calls) == 1
    element = enriched.elements[0]
    assert "Visual description:" in element.surrogate_text
    assert "feedback connection" in element.surrogate_text
    assert element.caption == "Fig. 1. Closed-loop architecture."
    assert element.metadata["visual_description_status"] == "generated"
    assert element.metadata["visual_description_provider"] == "fake_vlm"
    assert element.metadata["visual_description_model"] == "fake-vision-model"
    assert enriched.metadata["image_understanding_applied"] is True
    assert enriched.metadata["visual_description_generated_count"] == 1

    chunk = build_multimodal_chunks(
        enriched,
        start_index=0,
        chunker_version="test-chunker",
    )[0]
    evidence = build_evidence_item(RetrievalCandidate(chunk=chunk, rank=1))
    assert evidence.metadata["visual_description_status"] == "generated"
    assert "feedback connection" in evidence.metadata["visual_description"]
    assert evidence.metadata["visual_description_model"] == "fake-vision-model"


def test_disabled_visual_understanding_never_calls_provider(tmp_path: Path) -> None:
    provider = FakeVisualProvider()
    config = _config(enabled=False)

    enriched = enrich_document_with_visual_descriptions(
        _document(tmp_path),
        config=config,
        provider=provider,
    )

    assert provider.calls == []
    assert enriched.elements[0].metadata["visual_description_status"] == "disabled"
    assert "Visual description:" not in enriched.elements[0].surrogate_text
    assert enriched.metadata["image_understanding_enabled"] is False


def test_visual_provider_failure_falls_back_to_caption_surrogate(tmp_path: Path) -> None:
    provider = FakeVisualProvider(fail=True)
    original = _document(tmp_path)
    original_surrogate = original.elements[0].surrogate_text

    enriched = enrich_document_with_visual_descriptions(
        original,
        config=_config(),
        provider=provider,
    )

    element = enriched.elements[0]
    assert element.surrogate_text == original_surrogate
    assert element.metadata["visual_description_status"] == "failed"
    assert "synthetic VLM failure" in element.metadata["visual_description_error"]
    assert enriched.metadata["visual_description_failed_count"] == 1
    assert enriched.metadata["image_understanding_applied"] is False


def test_unavailable_provider_and_image_limit_are_nonfatal(tmp_path: Path) -> None:
    document = _document(tmp_path)
    second = document.elements[0].model_copy(
        update={"element_id": "element-2"}
    )
    document = document.model_copy(update={"elements": [document.elements[0], second]})

    unavailable = enrich_document_with_visual_descriptions(
        document,
        config=_config(),
        provider=None,
    )
    assert {
        element.metadata["visual_description_status"]
        for element in unavailable.elements
    } == {"unavailable"}

    provider = FakeVisualProvider()
    bounded = enrich_document_with_visual_descriptions(
        document,
        config=_config(max_images_per_document=1),
        provider=provider,
    )
    assert len(provider.calls) == 1
    assert bounded.elements[0].metadata["visual_description_status"] == "generated"
    assert bounded.elements[1].metadata["visual_description_status"] == "limit_skipped"


def test_visual_index_fingerprint_changes_with_semantic_config_and_disabled_is_stable() -> None:
    first = visual_description_index_version(_config(model="vision-a"))
    second = visual_description_index_version(_config(model="vision-b"))
    bounded = visual_description_index_version(_config(model="vision-a", max_output_tokens=96))

    assert first != second
    assert first != bounded
    assert visual_description_index_version(
        RagVisualUnderstandingConfig()
    ).endswith("-off")


def test_openai_compatible_visual_provider_sends_image_data_url(tmp_path: Path) -> None:
    image = tmp_path / "figure.png"
    image.write_bytes(_TINY_PNG)
    client = FakeCompletionClient()
    provider = OpenAICompatibleVisualDescriptionProvider(
        _config(detail="high"),
        client=client,
    )

    description = provider.describe(
        image_path=image,
        title="Control paper",
        caption="Fig. 1. Response comparison.",
        page_number=3,
        section_path=["Results"],
    )

    assert description.startswith("A line chart")
    assert len(client.calls) == 1
    call = client.calls[0]
    messages = call["messages"]
    user_content = messages[1]["content"]
    assert user_content[0]["type"] == "text"
    assert "Response comparison" in user_content[0]["text"]
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user_content[1]["image_url"]["detail"] == "high"


class FakeParser:
    def __init__(self, document: NormalizedDocument) -> None:
        self.document = document
        self.calls = 0

    def __call__(self, _path: str | Path) -> NormalizedDocument:
        self.calls += 1
        return self.document.model_copy(deep=True)


class EmptyTextChunker:
    version = "empty-text-v1"

    def chunk(self, _document: NormalizedDocument) -> list[DocumentChunk]:
        return []


class FakeEmbeddingProvider:
    model_name = "fake-embedding"
    dimension = 4

    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.chunks: dict[str, DocumentChunk] = {}

    def upsert_chunks(self, chunks, vectors) -> None:
        assert len(chunks) == len(vectors)
        self.chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def delete_chunks(self, chunk_ids) -> None:
        for chunk_id in chunk_ids:
            self.chunks.pop(chunk_id, None)

    def delete_document(self, document_id: str) -> None:
        self.chunks = {
            key: value
            for key, value in self.chunks.items()
            if value.document_id != document_id
        }


def test_index_reuse_happens_before_repeated_vlm_call(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF mock")
    document = _document(tmp_path)
    document = document.model_copy(
        update={
            "document": document.document.model_copy(
                update={
                    "source_uri": source.as_uri(),
                    "content_hash": "stable-content-hash",
                }
            )
        }
    )
    parser = FakeParser(document)
    provider = FakeVisualProvider()
    embedding = FakeEmbeddingProvider()
    store = FakeVectorStore()
    service = IndexService(
        chunker=EmptyTextChunker(),
        embedding_provider=embedding,
        vector_store=store,
        manifest=IndexManifest(tmp_path / "manifest.json"),
        parser=parser,
        visual_description_provider=provider,
        visual_understanding_config=_config(),
    )

    first = service.index_document(source)
    second = service.index_document(source)

    assert first.status is IndexStatus.READY
    assert second.status is IndexStatus.READY
    assert second.reused_existing is True
    assert len(provider.calls) == 1
    assert embedding.calls == 1
