from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.agent_context_builder import AgentContextBuilder
from backend.services.knowledge_graph_repository import KnowledgeGraphRepository


@dataclass(frozen=True)
class AgentKnowledgeContext:
    query: str
    context: str
    citations: list[dict[str, Any]]


class AgentKnowledgeRuntime:
    """Bridge between Agent Runtime and Knowledge Runtime.

    Keeps knowledge retrieval independent from execution while providing a
    stable context injection boundary for Planner/Reader/Translation agents.
    """

    def __init__(self, repository: KnowledgeGraphRepository | None = None):
        self.builder = AgentContextBuilder(repository)

    def build_context(self, query: str, top_k: int = 5) -> AgentKnowledgeContext:
        payload = self.builder.build(query, top_k)
        return AgentKnowledgeContext(
            query=query,
            context=payload.get("context", ""),
            citations=payload.get("citations", []),
        )


__all__ = ["AgentKnowledgeRuntime", "AgentKnowledgeContext"]
