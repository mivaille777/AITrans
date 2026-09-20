from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.models.agent_tasks import ScopeContext, ScopeMode
from backend.services.agent_context_builder import AgentContextBuilder
from backend.services.knowledge_graph_repository import KnowledgeGraphRepository


@dataclass(frozen=True)
class AgentKnowledgeContext:
    query: str
    context: str
    citations: list[dict[str, Any]]


class AgentKnowledgeRuntime:
    """Bridge between Agent Runtime and Knowledge Runtime."""

    def __init__(self, repository: KnowledgeGraphRepository | None = None):
        self.builder = AgentContextBuilder(repository)

    def build_context(
        self,
        query: str,
        top_k: int = 5,
        *,
        scope: ScopeContext | None = None,
    ) -> AgentKnowledgeContext:
        if scope is not None and scope.mode is ScopeMode.RESTRICTED and not scope.allowed_item_ids:
            return AgentKnowledgeContext(query=query, context="", citations=[])
        allowed_node_ids = (
            set(scope.allowed_item_ids)
            if scope is not None and scope.mode is ScopeMode.RESTRICTED
            else None
        )
        payload = self.builder.build(
            query,
            top_k=top_k,
            allowed_node_ids=allowed_node_ids,
        )
        return AgentKnowledgeContext(
            query=query,
            context=payload.get("context", ""),
            citations=payload.get("citations", []),
        )


__all__ = ["AgentKnowledgeContext", "AgentKnowledgeRuntime"]
