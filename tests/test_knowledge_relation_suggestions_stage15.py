from __future__ import annotations

import json

from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeRelationOrigin,
    KnowledgeRelationSuggestionStatus,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRelationSuggestionRepository,
    SqliteKnowledgeRepository,
)
from backend.services.knowledge_relation_suggestion_service import (
    KnowledgeRelationSuggestionService,
)


class _FakeClient:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload, ensure_ascii=False)


class _FakeProvider:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client


class _FakeTextService:
    provider_name = "fake"
    model = "fake-stage15"

    def __init__(self, payload) -> None:
        self.provider = _FakeProvider(_FakeClient(payload))

    def close(self) -> None:
        return None


def _service(tmp_path, payload):
    path = tmp_path / "knowledge.sqlite3"
    workspace = KnowledgeWorkspaceService(SqliteKnowledgeRepository(path))
    suggestions = KnowledgeRelationSuggestionService(
        workspace=workspace,
        repository=SqliteKnowledgeRelationSuggestionRepository(path),
        text_service=_FakeTextService(payload),
    )
    return workspace, suggestions


def test_ai_suggestion_stays_pending_until_user_accepts(tmp_path) -> None:
    workspace, service = _service(tmp_path, [])
    paper = workspace.create_item(
        item_type=KnowledgeItemType.PAPER,
        title="Safe BO",
        summary="The method enforces explicit safety constraints during Bayesian optimization.",
    )
    concept = workspace.create_item(
        item_type=KnowledgeItemType.CONCEPT,
        title="Safety gate",
        summary="A safety gate rejects candidates that violate operating constraints.",
    )
    service._text_service.provider.client.payload = [
        {
            "source_item_id": concept.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "explains",
            "label": "Explains the paper safety mechanism",
            "confidence": 0.88,
            "rationale": "The concept describes the explicit safety rejection mechanism used by the paper.",
            "evidence_item_ids": [concept.item_id, paper.item_id],
        }
    ]

    generated = service.generate(focus_item_id=paper.item_id)
    assert len(generated) == 1
    suggestion = generated[0]
    assert suggestion.status is KnowledgeRelationSuggestionStatus.PENDING
    assert workspace.list_relations() == []
    assert suggestion.metadata["prompt_id"].startswith("knowledge.relation_suggestion@")

    accepted, relation = service.accept(suggestion.suggestion_id)
    assert accepted.status is KnowledgeRelationSuggestionStatus.ACCEPTED
    assert accepted.accepted_relation_id == relation.relation_id
    assert relation.origin is KnowledgeRelationOrigin.AI
    assert relation.metadata["suggestion_id"] == suggestion.suggestion_id
    assert relation.metadata["evidence_item_ids"] == [concept.item_id, paper.item_id]


def test_reject_keeps_canonical_graph_unchanged(tmp_path) -> None:
    workspace, service = _service(tmp_path, [])
    paper = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    note = workspace.create_item(item_type=KnowledgeItemType.NOTE, title="Note")
    service._text_service.provider.client.payload = [
        {
            "source_item_id": note.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "related_to",
            "confidence": 0.61,
            "rationale": "The note and paper discuss the same mechanism.",
            "evidence_item_ids": [note.item_id, paper.item_id],
        }
    ]

    suggestion = service.generate(focus_item_id=paper.item_id)[0]
    rejected = service.reject(suggestion.suggestion_id)

    assert rejected.status is KnowledgeRelationSuggestionStatus.REJECTED
    assert rejected.accepted_relation_id is None
    assert workspace.list_relations() == []


def test_generator_filters_existing_duplicate_and_non_focus_edges(tmp_path) -> None:
    workspace, service = _service(tmp_path, [])
    paper = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    note = workspace.create_item(item_type=KnowledgeItemType.NOTE, title="Note")
    concept = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Concept")
    workspace.create_relation(
        source_item_id=note.item_id,
        target_item_id=paper.item_id,
        relation_type="supports",
    )
    service._text_service.provider.client.payload = [
        {
            "source_item_id": note.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "supports",
            "confidence": 0.9,
            "rationale": "Duplicate canonical edge.",
            "evidence_item_ids": [note.item_id, paper.item_id],
        },
        {
            "source_item_id": note.item_id,
            "target_item_id": concept.item_id,
            "relation_type": "explains",
            "confidence": 0.8,
            "rationale": "Does not involve focus.",
            "evidence_item_ids": [note.item_id, concept.item_id],
        },
        {
            "source_item_id": concept.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "extends",
            "confidence": 0.77,
            "rationale": "Valid local proposal.",
            "evidence_item_ids": [concept.item_id, paper.item_id],
        },
    ]

    generated = service.generate(focus_item_id=paper.item_id)
    assert [(item.source_item_id, item.target_item_id, item.relation_type) for item in generated] == [
        (concept.item_id, paper.item_id, "extends")
    ]


def test_accept_reuses_relation_created_after_suggestion(tmp_path) -> None:
    workspace, service = _service(tmp_path, [])
    paper = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    concept = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Concept")
    service._text_service.provider.client.payload = [
        {
            "source_item_id": concept.item_id,
            "target_item_id": paper.item_id,
            "relation_type": "explains",
            "confidence": 0.72,
            "rationale": "Proposal.",
            "evidence_item_ids": [concept.item_id, paper.item_id],
        }
    ]
    suggestion = service.generate(focus_item_id=paper.item_id)[0]
    manual = workspace.create_relation(
        source_item_id=concept.item_id,
        target_item_id=paper.item_id,
        relation_type="explains",
    )

    accepted, relation = service.accept(suggestion.suggestion_id)
    assert relation.relation_id == manual.relation_id
    assert accepted.accepted_relation_id == manual.relation_id
