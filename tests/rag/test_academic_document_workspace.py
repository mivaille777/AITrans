from __future__ import annotations

from backend.rag.config import RagConfig
from backend.rag.index_manifest import IndexManifest, IndexManifestRecord, IndexStatus
from backend.services.knowledge_library_service import KnowledgeLibraryService


def test_academic_workspace_builds_outline_and_section_preview(tmp_path) -> None:
    source = tmp_path / "paper.md"
    source.write_text(
        "# A Test Paper\n\n"
        "## Introduction\n\n"
        "This section introduces a constrained optimization problem.\n\n"
        "## Method\n\n"
        "The method combines retrieval evidence with bounded reasoning.\n\n"
        "### Objective\n\n"
        "The objective measures task quality under constraints.\n",
        encoding="utf-8",
    )
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(
        IndexManifestRecord(
            document_id="doc-academic",
            content_hash="hash-academic",
            source_uri=source.as_uri(),
            title="A Test Paper",
            status=IndexStatus.READY,
            chunk_ids=["chunk-1", "chunk-2"],
        )
    )
    service = KnowledgeLibraryService(
        index_service=object(),  # type: ignore[arg-type]
        manifest=manifest,
        config=RagConfig(),
        embedding_provider=object(),  # type: ignore[arg-type]
        allowed_roots=(tmp_path,),
    )

    outline = service.get_document_outline("doc-academic")

    assert outline is not None
    assert outline.document_id == "doc-academic"
    assert outline.title == "A Test Paper"
    headings = [section.heading for section in outline.sections]
    assert "Introduction" in headings
    assert "Method" in headings
    assert "Objective" in headings

    method = next(section for section in outline.sections if section.heading == "Method")
    preview = service.get_document_section("doc-academic", method.section_id)

    assert preview is not None
    assert preview.document_id == "doc-academic"
    assert preview.heading == "Method"
    assert "retrieval evidence" in preview.text
    assert preview.truncated is False


def test_academic_workspace_returns_none_for_unknown_document(tmp_path) -> None:
    service = KnowledgeLibraryService(
        index_service=object(),  # type: ignore[arg-type]
        manifest=IndexManifest(tmp_path / "manifest.json"),
        config=RagConfig(),
        embedding_provider=object(),  # type: ignore[arg-type]
        allowed_roots=(tmp_path,),
    )

    assert service.get_document_outline("missing") is None
    assert service.get_document_section("missing", "section") is None
