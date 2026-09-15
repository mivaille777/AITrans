from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.knowledge_relation_suggestion_dependencies import (
    get_knowledge_relation_suggestion_service,
)
from backend.api.knowledge_relation_suggestions import router
from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRelationSuggestionRepository,
    SqliteKnowledgeRepository,
)
from backend.services.knowledge_relation_suggestion_service import (
    KnowledgeRelationSuggestionService,
)


class _FakeClient:
    def __init__(self) -> None:
        self.payload = []

    def complete(self, **_kwargs):
        return json.dumps(self.payload, ensure_ascii=False)


class _FakeTextService:
    provider_name = "fake"
    model = "fake-stage15"

    def __init__(self) -> None:
        client = _FakeClient()
        self.provider = type("Provider", (), {"client": client})()

    def close(self) -> None:
        return None


def _client(tmp_path):
    path = tmp_path / "knowledge.sqlite3"
    workspace = KnowledgeWorkspaceService(SqliteKnowledgeRepository(path))
    text_service = _FakeTextService()
    service = KnowledgeRelationSuggestionService(
        workspace=workspace,
        repository=SqliteKnowledgeRelationSuggestionRepository(path),
        text_service=text_service,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_knowledge_relation_suggestion_service] = lambda: service
    return TestClient(app), workspace, text_service


def test_api_generates_lists_accepts_and_rejects_suggestions(tmp_path) -> None:
    client, workspace, text_service = _client(tmp_path)
    paper = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    concept = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Concept")
    note = workspace.create_item(item_type=KnowledgeItemType.NOTE, title="Note")
    text_service.provider.client.payload = [
        {
            "source_item_id": concept.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "explains",
            "confidence": 0.8,
            "rationale": "Concept explains the paper mechanism.",
            "evidence_item_ids": [concept.item_id, paper.item_id],
        },
        {
            "source_item_id": note.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "related_to",
            "confidence": 0.6,
            "rationale": "Note is topically related.",
            "evidence_item_ids": [note.item_id, paper.item_id],
        },
    ]

    generated = client.post(
        "/api/knowledge/relation-suggestions/generate",
        json={"focus_item_id": paper.item_id, "max_suggestions": 4},
    )
    assert generated.status_code == 201
    suggestions = generated.json()["suggestions"]
    assert len(suggestions) == 2
    assert workspace.list_relations() == []

    pending = client.get(
        "/api/knowledge/relation-suggestions",
        params={"focus_item_id": paper.item_id, "status": "pending"},
    )
    assert pending.status_code == 200
    assert pending.json()["total"] == 2

    accepted = client.post(
        f"/api/knowledge/relation-suggestions/{suggestions[0]['suggestion_id']}/accept"
    )
    assert accepted.status_code == 200
    assert accepted.json()["suggestion"]["status"] == "accepted"
    assert accepted.json()["relation"]["origin"] == "ai"

    rejected = client.post(
        f"/api/knowledge/relation-suggestions/{suggestions[1]['suggestion_id']}/reject"
    )
    assert rejected.status_code == 200
    assert rejected.json()["suggestion"]["status"] == "rejected"
    assert rejected.json()["relation"] is None

    assert len(workspace.list_relations()) == 1


def test_api_rejects_second_decision_on_same_suggestion(tmp_path) -> None:
    client, workspace, text_service = _client(tmp_path)
    paper = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    concept = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Concept")
    text_service.provider.client.payload = [
        {
            "source_item_id": concept.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "explains",
            "confidence": 0.8,
            "rationale": "Concept explains paper.",
            "evidence_item_ids": [concept.item_id, paper.item_id],
        }
    ]
    suggestion = client.post(
        "/api/knowledge/relation-suggestions/generate",
        json={"focus_item_id": paper.item_id},
    ).json()["suggestions"][0]

    assert client.post(
        f"/api/knowledge/relation-suggestions/{suggestion['suggestion_id']}/reject"
    ).status_code == 200
    again = client.post(
        f"/api/knowledge/relation-suggestions/{suggestion['suggestion_id']}/accept"
    )
    assert again.status_code == 422
    assert "no longer pending" in again.json()["detail"]
