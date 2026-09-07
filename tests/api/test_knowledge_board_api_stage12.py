from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.knowledge_board_dependencies import get_knowledge_board_service
from backend.api.knowledge_boards import router as board_router
from backend.api.knowledge_relations import router as relation_router
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRepository,
)
from backend.knowledge.board_repository import SqliteKnowledgeBoardRepository
from backend.knowledge.board_service import KnowledgeBoardService


def _client(tmp_path):
    path = tmp_path / "knowledge_workspace.sqlite3"
    workspace = KnowledgeWorkspaceService(SqliteKnowledgeRepository(path))
    boards = KnowledgeBoardService(SqliteKnowledgeBoardRepository(path), workspace)
    app = FastAPI()
    app.include_router(board_router)
    app.include_router(relation_router)
    app.dependency_overrides[get_knowledge_workspace_service] = lambda: workspace
    app.dependency_overrides[get_knowledge_board_service] = lambda: boards
    return TestClient(app), workspace


def test_board_api_persists_card_position_and_size(tmp_path) -> None:
    client, workspace = _client(tmp_path)
    item = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="BO Paper")

    boards = client.get("/api/knowledge/boards").json()["boards"]
    board_id = boards[0]["board_id"]
    response = client.put(
        f"/api/knowledge/boards/{board_id}/nodes/{item.item_id}",
        json={"x": 140, "y": 220, "width": 300, "height": 180, "z_index": 2},
    )
    assert response.status_code == 200

    snapshot = client.get(f"/api/knowledge/boards/{board_id}").json()
    assert snapshot["nodes"][0]["item_id"] == item.item_id
    assert snapshot["nodes"][0]["x"] == 140
    assert snapshot["nodes"][0]["width"] == 300


def test_relation_api_creates_and_deletes_manual_relation(tmp_path) -> None:
    client, workspace = _client(tmp_path)
    paper = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    concept = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Safe BO")

    created = client.post(
        "/api/knowledge/relations",
        json={
            "source_item_id": paper.item_id,
            "target_item_id": concept.item_id,
            "relation_type": "uses",
        },
    )
    assert created.status_code == 201
    relation_id = created.json()["relation_id"]
    assert created.json()["origin"] == "manual"

    listed = client.get("/api/knowledge/relations").json()
    assert listed["total"] == 1

    deleted = client.delete(f"/api/knowledge/relations/{relation_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_board_rejects_unknown_item(tmp_path) -> None:
    client, _ = _client(tmp_path)
    board_id = client.get("/api/knowledge/boards").json()["boards"][0]["board_id"]

    response = client.put(
        f"/api/knowledge/boards/{board_id}/nodes/missing",
        json={"x": 0, "y": 0},
    )
    assert response.status_code == 422
    assert "knowledge item" in response.json()["detail"]
