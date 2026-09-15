from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.knowledge_graph_repository import KnowledgeGraphRepository


@dataclass(frozen=True)
class KnowledgeEvidence:
    id: str
    title: str
    type: str
    score: float
    reason: str


class AgentKnowledgeRetriever:
    """Graph-aware retrieval facade for Agent Runtime.

    This layer combines explicit knowledge relations with future vector
    retrieval results. It intentionally keeps graph reasoning separate from
    the document indexing pipeline.
    """

    def __init__(self, repository: KnowledgeGraphRepository | None = None):
        self.repository = repository or KnowledgeGraphRepository()

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        graph = self.repository.get_graph()
        query_terms = set(query.lower().split())
        scored: list[KnowledgeEvidence] = []

        for node in graph.get("nodes", []):
            text = " ".join(
                [
                    str(node.get("title", "")),
                    str(node.get("summary", "")),
                    str(node.get("type", "")),
                ]
            ).lower()
            overlap = len(query_terms.intersection(set(text.split())))
            relation_bonus = self._relation_bonus(node.get("id"), graph)
            score = min(1.0, overlap * 0.2 + relation_bonus)
            if score > 0:
                scored.append(
                    KnowledgeEvidence(
                        id=node.get("id", ""),
                        title=node.get("title", ""),
                        type=node.get("type", ""),
                        score=score,
                        reason="keyword match with graph relation support",
                    )
                )

        scored.sort(key=lambda item: item.score, reverse=True)
        return [item.__dict__ for item in scored[:top_k]]

    @staticmethod
    def _relation_bonus(node_id: str, graph: dict[str, Any]) -> float:
        count = sum(
            1
            for edge in graph.get("edges", [])
            if edge.get("source") == node_id or edge.get("target") == node_id
        )
        return min(0.4, count * 0.05)


__all__ = ["AgentKnowledgeRetriever", "KnowledgeEvidence"]
