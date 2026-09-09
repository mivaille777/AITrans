from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class KnowledgeInjector:
    """Inject Knowledge Runtime outputs into a shared multi-agent context.

    Stage 4's ``AgentKnowledgeRuntime.build_context`` returns an
    ``AgentKnowledgeContext`` dataclass, while tests and future adapters may
    return dictionaries. This adapter deliberately accepts both shapes so the
    multi-agent layer stays decoupled from the concrete knowledge runtime.
    """

    def __init__(self, knowledge_runtime=None, *, top_k: int = 5):
        self.knowledge_runtime = knowledge_runtime
        self.top_k = max(1, int(top_k))

    @staticmethod
    def _value(result: Any, key: str, default: Any = None) -> Any:
        if isinstance(result, Mapping):
            return result.get(key, default)
        return getattr(result, key, default)

    @staticmethod
    def _citation_key(citation: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(citation.get("id", "") or ""),
            str(citation.get("title", "") or ""),
            str(citation.get("source_type", "") or ""),
        )

    def inject(self, query: str, context: Any):
        if self.knowledge_runtime is None or context is None:
            return context

        result = self.knowledge_runtime.build_context(query, top_k=self.top_k)

        knowledge_text = str(
            self._value(result, "context", self._value(result, "context_text", "")) or ""
        ).strip()
        if knowledge_text:
            context.knowledge_context = knowledge_text

        citations = self._value(result, "citations", []) or []
        existing = {
            self._citation_key(item)
            for item in getattr(context, "citations", [])
            if isinstance(item, dict)
        }
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            key = self._citation_key(citation)
            if key in existing:
                continue
            context.add_citation(dict(citation))
            existing.add(key)

        nodes = self._value(
            result,
            "nodes",
            self._value(result, "retrieved_nodes", None),
        )
        if nodes is not None:
            context.memory["knowledge_nodes"] = list(nodes)

        context.memory["knowledge_query"] = str(query or "")
        context.memory["knowledge_citation_count"] = len(context.citations)
        return context


__all__ = ["KnowledgeInjector"]
