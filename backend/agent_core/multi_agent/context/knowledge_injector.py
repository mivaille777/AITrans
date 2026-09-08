from __future__ import annotations

from typing import Any


class KnowledgeInjector:
    """Inject Knowledge Runtime outputs into shared agent context."""

    def __init__(self, knowledge_runtime=None):
        self.knowledge_runtime = knowledge_runtime

    def inject(self, query: str, context: Any):
        if self.knowledge_runtime is None:
            return context

        try:
            result = self.knowledge_runtime.build_context(query)
        except Exception:
            return context

        if isinstance(result, dict):
            context.knowledge_context = result.get("context", "")
            context.citations.extend(result.get("citations", []))
            context.memory["knowledge_nodes"] = result.get("nodes", [])

        return context


__all__ = ["KnowledgeInjector"]
