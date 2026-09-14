from __future__ import annotations

from types import SimpleNamespace

from backend.agent_tools.base import AgentToolInvocationContext, EmptyToolArgs
from backend.agent_tools.knowledge import KnowledgeAgentTools
from backend.knowledge.domain import KnowledgeItem, KnowledgeItemType


class StubWorkspaceService:
    def __init__(self, source: KnowledgeItem) -> None:
        self.source = source
        self.created: list[dict[str, object]] = []
        self.relations: list[dict[str, object]] = []

    def get_item(self, item_id: str):
        return self.source if item_id == self.source.item_id else None

    def create_item(self, **kwargs):
        self.created.append(dict(kwargs))
        return KnowledgeItem(
            item_id="insight-1",
            item_type=kwargs["item_type"],
            title=kwargs["title"],
            summary=kwargs["summary"],
            resource_document_id=kwargs.get("resource_document_id"),
            source_uri=kwargs.get("source_uri", ""),
            metadata=kwargs.get("metadata", {}),
        )

    def create_relation(self, **kwargs):
        self.relations.append(dict(kwargs))
        return SimpleNamespace(relation_id="relation-1")

    def delete_item(self, _item_id: str):
        return True


def test_agent_insight_inherits_reader_document_and_section_grounding() -> None:
    source = KnowledgeItem(
        item_id="evidence-1",
        item_type=KnowledgeItemType.EVIDENCE,
        title="Bounded optimization evidence",
        summary="Selected evidence.",
        source_uri="file:///paper.pdf",
        metadata={
            "document_id": "doc-1",
            "section_id": "sec-method",
            "section_heading": "Methods",
            "page_start": 3,
            "page_end": 4,
            "selection_text": "Selected evidence.",
            "context_before": "Before evidence.",
            "context_after": "After evidence.",
        },
    )
    workspace = StubWorkspaceService(source)
    tools = KnowledgeAgentTools(
        retrieval_service=None,
        workspace_service=workspace,  # type: ignore[arg-type]
    )

    result = tools.save_knowledge_card(
        AgentToolInvocationContext(
            knowledge_item_id="evidence-1",
            knowledge_writeback_type="insight",
            knowledge_writeback_operation="research",
            knowledge_relation_type="derived_from",
            ai_content="The evidence supports bounded local refinement.",
            request_id=42,
            run_id="run-42",
        ),
        EmptyToolArgs(),
    )

    assert result.effect == "write"
    assert result.data is not None
    assert result.data["source_item_id"] == "evidence-1"
    created = workspace.created[0]
    assert created["resource_document_id"] == "doc-1"
    metadata = created["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["document_id"] == "doc-1"
    assert metadata["section_id"] == "sec-method"
    assert metadata["section_heading"] == "Methods"
    assert metadata["page_start"] == 3
    assert metadata["page_end"] == 4
    assert metadata["context_before"] == "Before evidence."
    assert metadata["context_after"] == "After evidence."
    assert "selection_text" not in metadata
    assert metadata["sources"] == [
        {
            "document_id": "doc-1",
            "source_uri": "file:///paper.pdf",
            "section": "Methods",
            "page": 3,
        }
    ]
    assert workspace.relations[0]["source_item_id"] == "insight-1"
    assert workspace.relations[0]["target_item_id"] == "evidence-1"
    assert workspace.relations[0]["relation_type"] == "derived_from"
