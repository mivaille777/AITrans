from __future__ import annotations

from typing import Any


class AgentContextBuilder:
    """Build grounded agent context from graph retrieval evidence.

    Keeps retrieved knowledge separate from the generation layer so future
    LLM providers, rerankers and citation systems can be plugged in.
    """

    def build(self, query: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        citations = [
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "source_type": item.get("type", ""),
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
