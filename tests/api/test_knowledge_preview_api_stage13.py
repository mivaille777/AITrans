from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.knowledge_dependencies import get_knowledge_library_service
from backend.api.knowledge_preview import router


class _FakeKnowledgeLibraryService:
    def __init__(self, source: Path, *, source_uri: str | None = None) -> None:
        self.source = source
        self.record = SimpleNamespace(
            document_id="doc-stage13",
            source_uri=source_uri or source.resolve().as_uri(),
        )

    def get_document(self, document_id: str):
        return self.record if document_id == self.record.document_id else None

    def validate_source_path(self, source_path: str | Path) -> Path:
        path = Path(source_path).resolve(strict=True)
        if path != self.source.resolve():
            raise PermissionError("document path is outside allowed knowledge roots")
        return path


def _client(service: _FakeKnowledgeLibraryService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_knowledge_library_service] = lambda: service
    return TestClient(app)


def test_registered_pdf_can_be_streamed_for_inline_reader_preview(tmp_path) -> None:
    source = tmp_path / "paper.pdf"
    payload = b"%PDF-1.4\n% stage13 preview\n"
    source.write_bytes(payload)
    client = _client(_FakeKnowledgeLibraryService(source))

    response = client.get("/api/knowledge/documents/doc-stage13/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == payload


def test_preview_rejects_non_pdf_registered_document(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("notes", encoding="utf-8")
    client = _client(_FakeKnowledgeLibraryService(source))

    response = client.get("/api/knowledge/documents/doc-stage13/preview")

    assert response.status_code == 422
    assert "only for PDF" in response.json()["detail"]


def test_preview_rejects_unknown_document(tmp_path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    client = _client(_FakeKnowledgeLibraryService(source))

    response = client.get("/api/knowledge/documents/missing/preview")

    assert response.status_code == 404
