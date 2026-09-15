from __future__ import annotations

from typing import Any

from backend.services.agent_knowledge_retrieval import AgentKnowledgeRetriever


class AgentContextBuilder:
    """Build grounded agent context from knowledge retrieval evidence.

    The builder owns the transformation from retrieved evidence into an
    agent-consumable context package. Retrieval dependencies are injected so
    the runtime layer can compose Knowledge Graph, RAG and future rerankers.
    """

    def __init__(self, repository: Any | None = None):
        # AgentKnowledgeRetriever already supplies the default repository when
        # ``repository`` is None. Always construct it so the default runtime
        # performs real retrieval instead of silently returning empty context.
        self.retriever = AgentKnowledgeRetriever(repository)

    def build(
        self,
        query: str,
        top_k: int = 5,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if evidence is None:
            evidence = self.retriever.retrieve(query, top_k=top_k)

        citations = [
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "source_type": item.get("type", item.get("source_type", "")),
                "score": item.get("score", 0.0),
            }
            for item in evidence
        ]

        context = "\n".join(
            f"[{item['id']}] {item['title']} ({item['source_type']})"
            for item in citations
        )

        return {
            "query": query,
            "context": context,
            "citations": citations,
        }


__all__ = ["AgentContextBuilder"]
