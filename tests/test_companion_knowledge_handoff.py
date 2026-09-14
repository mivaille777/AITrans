from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.dependencies import get_companion_handoff_service
from backend.main import create_app
from backend.services.companion_handoff_service import CompanionHandoffService


def test_companion_handoff_round_trips_bounded_knowledge_scope() -> None:
    app = create_app()
    service = CompanionHandoffService()
    app.dependency_overrides[get_companion_handoff_service] = lambda: service
    payload = {
        "source_text": "The evidence supports bounded local refinement.",
        "translated_text": "",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "knowledge-item://insight-1",
        "resource_title": "Research insight",
        "section_heading": "Methods",
        "context_before": "Before evidence.",
        "context_after": "After evidence.",
        "source_kind": "knowledge_insight",
        "ai_content": "The evidence supports bounded local refinement.",
        "ai_action": "knowledge_context",
        "suggested_prompt": "Develop this insight.",
        "knowledge_enabled": True,
        "knowledge_document_ids": ["doc-1", "doc-1", " doc-2 "],
    }

    with TestClient(app) as client:
        created = client.post("/api/companion/handoff", json=payload)
        current = client.get("/api/companion/handoff")

    assert created.status_code == 200
    assert created.json()["knowledge_enabled"] is True
    assert created.json()["knowledge_document_ids"] == ["doc-1", "doc-2"]
    assert current.status_code == 200
    assert current.json()["handoff"]["source_kind"] == "knowledge_insight"
    assert current.json()["handoff"]["knowledge_enabled"] is True
    assert current.json()["handoff"]["knowledge_document_ids"] == ["doc-1", "doc-2"]


def test_companion_handoff_disables_empty_knowledge_scope() -> None:
    service = CompanionHandoffService()

    state = service.create(
        source_text="Card-only context.",
        source_kind="knowledge_card",
        knowledge_enabled=True,
        knowledge_document_ids=[],
    )

    assert state.knowledge_enabled is False
    assert state.knowledge_document_ids == ()
