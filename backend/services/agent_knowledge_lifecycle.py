from __future__ import annotations

from typing import Any, Callable

from backend.agent_core.events import AgentEventType
from backend.agent_core.state import AgentState
from backend.services.agent_knowledge_context_service import AgentKnowledgeContextService


class AgentKnowledgeLifecycle:
    """Small lifecycle adapter for injecting grounded knowledge into agents.

    The adapter keeps retrieval/context assembly outside the core runtime while
    providing a stable integration point for future workflow graphs.
    """

    def __init__(
        self,
        context_service: AgentKnowledgeContextService | None = None,
    ) -> None:
        self.context_service = context_service or AgentKnowledgeContextService()

    def retrieve(
        self,
        state: AgentState,
        emit: Callable[[AgentEventType, dict[str, Any]], None] | None = None,
    ) -> AgentState:
        if emit:
            emit(
                AgentEventType.KNOWLEDGE_RETRIEVAL_STARTED,
                {"query": state.user_input},
            )

        context = self.context_service.build(
            query=state.user_input,
            top_k=5,
        )

        state.browser_context["knowledge_context"] = context.model_dump()
        state.sync_contract()

        if emit:
            emit(
                AgentEventType.KNOWLEDGE_RETRIEVED,
                {
                    "citations": len(context.citations),
                    "evidence": len(context.evidence),
                },
            )
            emit(
                AgentEventType.KNOWLEDGE_CONTEXT_READY,
                {"context_length": len(context.context_text)},
            )

        return state


__all__ = ["AgentKnowledgeLifecycle"]
