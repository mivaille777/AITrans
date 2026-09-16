from __future__ import annotations

import json

import pytest

from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRelationSuggestionRepository,
    SqliteKnowledgeRepository,
)
from backend.models.agent_tasks import ScopeContext
from backend.services.knowledge_relation_suggestion_service import (
    KnowledgeRelationSuggestionService,
)


class Client:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["user_prompt"])
        ids = [item["item_id"] for item in payload["items"]]
        return json.dumps(
            [
                {
                    "source_item_id": ids[0],
                    "target_item_id": ids[1],
                    "relation_type": "related_to",
                    "rationale": "Scoped test relation.",
                    "evidence_item_ids": ids,
                }
            ]
        )


class TextService:
    provider_name = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.provider = type("Provider", (), {"client": Client()})()


def test_relation_candidates_are_limited_to_authoritative_item_scope(tmp_path) -> None:
    path = tmp_path / "knowledge.sqlite3"
    workspace = KnowledgeWorkspaceService(SqliteKnowledgeRepository(path))
    focus = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Focus")
    allowed = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Allowed")
    private = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Private")
    text_service = TextService()
    service = KnowledgeRelationSuggestionService(
        workspace=workspace,
        repository=SqliteKnowledgeRelationSuggestionRepository(path),
        text_service=text_service,
    )
    scope = ScopeContext.issue(
        scope_revision="workspace-a-items",
        allowed_item_ids=[focus.item_id, allowed.item_id],
    )

    suggestions = service.generate(focus_item_id=focus.item_id, scope=scope)
    prompt = json.loads(text_service.provider.client.calls[0]["user_prompt"])

    assert {item["item_id"] for item in prompt["items"]} == {focus.item_id, allowed.item_id}
    assert private.item_id not in json.dumps(prompt)
    assert suggestions[0].target_item_id == allowed.item_id

    with pytest.raises(ValueError, match="outside"):
        service.generate(
            focus_item_id=focus.item_id,
            candidate_item_ids=[private.item_id],
            scope=scope,
        )
