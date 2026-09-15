from __future__ import annotations

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.api.dependencies import (
    get_companion_ownership_service,
    get_conversation_store_service,
    get_product_agent_service,
)
from backend.services.agent_conversation_service import AgentConversationService


def make_graph():
    """Build the production ReadingAgentGraph for LangSmith Studio.

    Agent Server graph factories may either accept no arguments or explicitly
    typed ``RunnableConfig`` / ``ServerRuntime`` parameters. Studio only needs
    the production topology here, so keep this factory argument-free and avoid
    ambiguous type-based injection during graph introspection.
    """

    conversation_service = AgentConversationService(
        store=get_conversation_store_service(),
        ownership=get_companion_ownership_service(),
    )
    adapter = ProductAgentRuntimeAdapter(
        get_product_agent_service(),
        conversation_service=conversation_service,
    )
    return ReadingAgentGraph(adapter).compiled_graph


__all__ = ["make_graph"]
