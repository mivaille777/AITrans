"""Knowledge V2 compatibility API contract tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.knowledge_v2_dependencies import get_knowledge_v2_service
from backend.knowledge.v2_repository import KnowledgeV2Repository
from backend.knowledge.v2_service import KnowledgeV2Service
from backend.main import create_app


EXPECTED_ROUTES = {
    "/api/knowledge/v2/cards",
    "/api/knowledge/v2/cards/{card_id}",
    "/api/knowledge/v2/graph",
    "/api/knowledge/v2/events",
}


def test_knowledge_v2_routes_are_registered_on_application():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert EXPECTED_ROUTES <= paths


def test_knowledge_v2_routes_project_canonical_cards(tmp_path: Path):
    repository = KnowledgeV2Repository(tmp_path / "knowledge.db")
    service = KnowledgeV2Service(repository)
    card = service.create_card(
        card_type="concept",
        title="Agentic RAG",
        summary="Agent controlled retrieval workflow",
        content={"scope": "research"},
        confidence=0.9,
    )

    app = create_app()
    app.dependency_overrides[get_knowledge_v2_service] = lambda: service

    with TestClient(app) as client:
        cards_response = client.get("/api/knowledge/v2/cards")
        card_response = client.get(f"/api/knowledge/v2/cards/{card['id']}")
        graph_response = client.get("/api/knowledge/v2/graph")
        events_response = client.get("/api/knowledge/v2/events")

    assert cards_response.status_code == 200
    assert cards_response.json()[0]["title"] == "Agentic RAG"
    assert card_response.status_code == 200
    assert card_response.json()["content"] == {"scope": "research"}
    assert graph_response.status_code == 200
    assert graph_response.json()["nodes"][0]["id"] == card["id"]
    assert events_response.status_code == 200
    assert events_response.json() == []
