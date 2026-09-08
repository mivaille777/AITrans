from __future__ import annotations

from typing import Any, Callable

from backend.agent_core.events import AgentEventType
from backend.agent_core.state import AgentState
from backend.services.agent_knowledge_lifecycle import AgentKnowledgeLifecycle


class AgentRuntimeKnowledgeHook:
    """Runtime hook that injects grounded knowledge context into AgentState.

    This adapter keeps knowledge retrieval outside the core execution engine while
    providing a single lifecycle entry point for workflow adapters.
    """

    def __init__(self, lifecycle: AgentKnowledgeLifecycle | None = None) -> None:
        self.lifecycle = lifecycle or AgentKnowledgeLifecycle()

    def apply(
        self,
        state: AgentState,
        *,
        emit: Callable[[AgentEventType, dict[str, Any]], None] | None = None,
    ) -> AgentState:
        if not state.route.needs_knowledge and not state.intent:
            return state

        if emit:
            emit(
                AgentEventType.KNOWLEDGE_RETRIEVAL_STARTED,
                {"query": state.user_input},
            )

        context = self.lifecycle.retrieve(state.user_input)
        state.browser_context["knowledge_context"] = context.model_dump()
        state.sync_contract()

        if emit:
            emit(
                AgentEventType.KNOWLEDGE_CONTEXT_READY,
                {
                    "citations": len(context.citations),
                    "evidence": len(context.evidence),
                },
            )

        return state


__all__ = ["AgentRuntimeKnowledgeHook"]
