from __future__ import annotations

from datetime import UTC, datetime

from backend.agent_core.orchestration.evidence_service import ScopedEvidenceService
from backend.knowledge.domain import KnowledgeItem, KnowledgeItemType, KnowledgeRelation
from backend.models.agent_tasks import ScopeContext
from backend.services.agent_knowledge_retrieval import AgentKnowledgeRetriever


class GraphRepository:
    def get_graph(self):
        return {
            "nodes": [
                {"id": "a", "title": "alpha method", "summary": "", "type": "concept"},
                {"id": "b", "title": "private beta", "summary": "", "type": "concept"},
                {"id": "c", "title": "unrelated", "summary": "", "type": "concept"},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
            ],
        }


def test_legacy_graph_retrieval_requires_text_relevance_and_scopes_edges() -> None:
    retriever = AgentKnowledgeRetriever(GraphRepository())

    restricted = retriever.retrieve("alpha", allowed_node_ids={"a"})
    unrelated = retriever.retrieve("missing", allowed_node_ids={"a", "b", "c"})

    assert [item["id"] for item in restricted] == ["a"]
    assert restricted[0]["score"] == 0.2  # cross-scope edge adds no bonus
    assert unrelated == []  # degree alone cannot introduce evidence


class Knowledge:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.items = {
            "a": KnowledgeItem(item_id="a", item_type=KnowledgeItemType.CONCEPT, title="alpha method", updated_at=now),
            "b": KnowledgeItem(item_id="b", item_type=KnowledgeItemType.CONCEPT, title="private beta", updated_at=now),
            "c": KnowledgeItem(item_id="c", item_type=KnowledgeItemType.CONCEPT, title="unrelated", updated_at=now),
        }
        self.relations = [
            KnowledgeRelation(relation_id="ab", source_item_id="a", target_item_id="b", relation_type="related_to"),
            KnowledgeRelation(relation_id="bc", source_item_id="b", target_item_id="c", relation_type="related_to"),
        ]

    def get_item(self, item_id: str):
        return self.items.get(item_id)

    def list_items(self):
        return list(self.items.values())

    def list_relations(self):
        return self.relations


def test_scoped_knowledge_relations_never_expand_outside_allowed_items() -> None:
    service = ScopedEvidenceService(knowledge_workspace=Knowledge())
    scope = ScopeContext.issue(
        scope_revision="items-a-b",
        allowed_item_ids=["a", "b"],
        source_versions={"a": "1", "b": "1"},
    )

    packets = service.retrieve_packets(query="alpha", scope=scope)

    assert [packet.evidence_ref.source_id for packet in packets] == ["a"]
    assert packets[0].relation_ids == ["ab"]
    assert all("c" not in packet.relation_ids for packet in packets)
