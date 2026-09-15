from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.knowledge_items import router
from backend.api.knowledge_dependencies import get_knowledge_library_service
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.knowledge import KnowledgeWorkspaceService, SqliteKnowledgeRepository


class _FakeLibraryService:
    def __init__(self) -> None:
        self.records = [
            SimpleNamespace(
                document_id="doc-pdf",
                title="Bayesian Optimization Paper",
                source_uri="file:///tmp/paper.pdf",
            ),
            SimpleNamespace(
                document_id="doc-docx",
                title="Experiment Notes",
                source_uri="file:///tmp/notes.docx",
            ),
        ]

    def list_documents(self):
        return list(self.records)


def _client(tmp_path) -> TestClient:
    workspace = KnowledgeWorkspaceService(
        SqliteKnowledgeRepository(tmp_path / "knowledge_workspace.sqlite3")
    )
    library = _FakeLibraryService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_knowledge_workspace_service] = lambda: workspace
    app.dependency_overrides[get_knowledge_library_service] = lambda: library
    return TestClient(app)


def test_list_items_syncs_indexed_resources_into_cards(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/knowledge/items")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    by_document = {item["resource_document_id"]: item for item in payload["items"]}
    assert by_document["doc-pdf"]["item_type"] == "paper"
    assert by_document["doc-docx"]["item_type"] == "document"


def test_create_update_and_delete_semantic_card(tmp_path) -> None:
    client = _client(tmp_path)

    created = client.post(
        "/api/knowledge/items",
        json={
            "item_type": "note",
            "title": "Safety constraint notes",
            "summary": "Keep the LLM inside a bounded reasoning role.",
        },
    )
    assert created.status_code == 201
    item_id = created.json()["item_id"]

    updated = client.patch(
        f"/api/knowledge/items/{item_id}",
        json={"title": "Bounded LLM reasoning"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Bounded LLM reasoning"

    deleted = client.delete(f"/api/knowledge/items/{item_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"item_id": item_id, "deleted": True}


def test_document_cards_cannot_be_created_without_resource_boundary(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/knowledge/items",
        json={"item_type": "document", "title": "Detached document"},
    )

    assert response.status_code == 422
    assert "source resource" in response.json()["detail"]
