from __future__ import annotations

import pytest

from backend.agent_tools.base import AgentToolInvocationContext, EmptyToolArgs
from backend.agent_tools.knowledge import KnowledgeAgentTools, build_knowledge_tool_definitions
from backend.knowledge.domain import KnowledgeItemType, KnowledgeRelationOrigin
from backend.knowledge.repository import SqliteKnowledgeRepository
from backend.knowledge.service import KnowledgeWorkspaceService


def _workspace(tmp_path) -> KnowledgeWorkspaceService:
    return KnowledgeWorkspaceService(SqliteKnowledgeRepository(tmp_path / "knowledge.sqlite3"))


def test_save_knowledge_card_writes_canonical_item_relation_and_provenance(tmp_path):
    workspace = _workspace(tmp_path)
    source = workspace.create_item(
        item_type=KnowledgeItemType.PAPER,
        title="Agent Planning",
        summary="Original paper card summary.",
        resource_document_id="doc-agent-planning",
        source_uri="file:///papers/agent-planning.pdf",
    )
    tools = KnowledgeAgentTools(
        retrieval_service=None,
        workspace_service=workspace,
    )

    result = tools.save_knowledge_card(
        AgentToolInvocationContext(
            source_text=source.summary,
            translated_text="Agent generated summary with the key planning insight.",
            resource_url=(
                f"knowledge-item://{source.item_id}"
                "?type=insight&operation=summarize&relation=derived_from"
            ),
            resource_title=source.title,
            source_kind="knowledge_card",
            request_id=7,
        ),
        EmptyToolArgs(),
    )

    assert result.effect == "write"
    assert result.tool_name == "save_knowledge_card"
    assert result.data is not None

    created = workspace.get_item(str(result.data["item_id"]))
    assert created is not None
    assert created.item_type is KnowledgeItemType.INSIGHT
    assert created.summary == "Agent generated summary with the key planning insight."
    assert created.source_uri == source.source_uri
    assert created.resource_document_id is None
    assert created.metadata["document_id"] == "doc-agent-planning"
    assert created.metadata["source_item_id"] == source.item_id
    assert created.metadata["provenance"]["created_by"] == "agent"
    assert created.metadata["provenance"]["operation"] == "summarize"
    assert created.metadata["sources"][0]["document_id"] == "doc-agent-planning"
    assert workspace.get_item(source.item_id) == source

    relation = workspace.get_relation(str(result.data["relation_id"]))
    assert relation is not None
    assert relation.source_item_id == created.item_id
    assert relation.target_item_id == source.item_id
    assert relation.relation_type == "derived_from"
    assert relation.origin is KnowledgeRelationOrigin.AI


def test_save_knowledge_card_rejects_resource_backed_target_type(tmp_path):
    workspace = _workspace(tmp_path)
    source = workspace.create_item(
        item_type=KnowledgeItemType.NOTE,
        title="Source note",
        summary="Source content",
    )
    tools = KnowledgeAgentTools(
        retrieval_service=None,
        workspace_service=workspace,
    )

    with pytest.raises(ValueError, match="cannot create a resource-backed"):
        tools.save_knowledge_card(
            AgentToolInvocationContext(
                source_text=source.summary,
                translated_text="Generated content",
                resource_url=f"knowledge-item://{source.item_id}?type=paper",
            ),
            EmptyToolArgs(),
        )


def test_save_knowledge_card_tool_requires_confirmation():
    tools = KnowledgeAgentTools(retrieval_service=None, workspace_service=None)
    definitions = {definition.spec.name: definition.spec for definition in build_knowledge_tool_definitions(tools)}

    spec = definitions["save_knowledge_card"]
    assert spec.effect == "write"
    assert spec.requires_confirmation is True
    assert spec.input_schema == {}
