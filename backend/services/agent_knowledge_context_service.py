from __future__ import annotations

from typing import Any

from backend.agent_core.knowledge_context import AgentKnowledgeContext


class AgentKnowledgeContextService:
    """Converts retrieval outputs into prompt-ready grounded context."""

    def build(
        self,
        *,
        query: str,
        retrieval_result: dict[str, Any] | None = None,
    ) -> AgentKnowledgeContext:
        payload = retrieval_result or {}
        evidence = list(payload.get("evidence", []) or [])
        citations = list(payload.get("citations", []) or [])
        results = list(payload.get("results", []) or [])

        nodes = [
            str(item.get("document_id", "") or item.get("id", ""))
            for item in results
            if isinstance(item, dict)
        ]

        context_text = str(payload.get("context", "") or "")
        if not context_text and results:
            context_text = "\n".join(
                str(item.get("text", "") or "")
                for item in results
                if isinstance(item, dict)
            )

        return AgentKnowledgeContext(
            query=query,
            context_text=context_text,
            evidence=evidence,
            citations=citations,
            retrieved_nodes=[item for item in nodes if item],
        )


__all__ = ["AgentKnowledgeContextService"]
