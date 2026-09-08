from __future__ import annotations

from .shared_context import SharedAgentContext


class SharedContextManager:
    """Manage context lifecycle across multiple agents."""

    def create(self, query: str) -> SharedAgentContext:
        return SharedAgentContext(query=query)

    def update_agent_result(
        self,
        context: SharedAgentContext,
        agent_name: str,
        result,
    ) -> SharedAgentContext:
        context.add_result(agent_name, result)
        return context


__all__ = ["SharedContextManager"]
