from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.dependencies import get_conversation_store_service
from backend.main import create_app
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.services.conversation_grounding_service import save_message_grounding
from backend.services.conversation_store_service import ConversationStoreService


def test_conversation_api_lists_gets_renames_and_deletes(tmp_path) -> None:
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    exchange = store.begin_exchange(
        session_id="session-1",
        user_message="Explain the anchor.",
        request_id=1,
        source_text="Selected text",
        translated_text="选中文本",
        resource_title="Paper",
        section_heading="Method",
    )
    store.finalize_message(
        exchange.assistant_message_id,
        status="complete",
        content="Explanation [1]",
        provider="stub-ai",
        model="stub-model",
    )
    evidence = AgentEvidenceItem(
        evidence_id="evidence-1",
        source_type="knowledge",
        source_id="doc-1",
        title="Control Paper",
        resource_url="file:///paper.pdf",
        location="Page 8 · Section Stability",
        excerpt="Evidence excerpt",
    )
    citation = AgentCitationRef(
        citation_id="citation-1",
        evidence_ids=["evidence-1"],
        label="[1]",
    )
    save_message_grounding(
        store.storage_path,
        exchange.assistant_message_id,
        knowledge_enabled=True,
        evidence=[evidence],
        citations=[citation],
    )

    app = create_app()
    app.dependency_overrides[get_conversation_store_service] = lambda: store

    with TestClient(app) as client:
        listed = client.get("/api/conversations?limit=10")
        detail = client.get(f"/api/conversations/{exchange.conversation_id}")
        renamed = client.patch(
            f"/api/conversations/{exchange.conversation_id}",
            json={"title": "Anchor discussion"},
        )
        deleted = client.delete(f"/api/conversations/{exchange.conversation_id}")
        missing = client.get(f"/api/conversations/{exchange.conversation_id}")

    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["conversation_id"] == exchange.conversation_id
    assert detail.status_code == 200
    assistant = detail.json()["messages"][-1]
    assert assistant["status"] == "complete"
    assert assistant["provider"] == "stub-ai"
    assert assistant["knowledge_enabled"] is True
    assert assistant["evidence"][0]["evidence_id"] == "evidence-1"
    assert assistant["citations"][0]["label"] == "[1]"
    assert renamed.json()["title"] == "Anchor discussion"
    assert deleted.json() == {
        "deleted": True,
        "conversation_id": exchange.conversation_id,
    }
    assert missing.status_code == 404
