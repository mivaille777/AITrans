from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from backend.agent_core.context import ReadingContextProvider
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.api.dependencies import (
    get_companion_ownership_service,
    get_conversation_store_service,
    get_product_agent_service,
    get_reading_selection_resolver,
    get_research_note_service,
    get_translation_service,
)
from backend.services.agent_conversation_service import AgentConversationService
from backend.services.agent_trace_store_service import AgentTraceStoreService
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService
from backend.services.product_agent_service import ProductAgentService
from backend.services.reading_selection_resolver import ReadingSelectionResolver
from backend.services.research_note_service import ResearchNoteService
from backend.services.translation_service import TranslationService

ProductAgentServiceDependency = Annotated[
    ProductAgentService,
    Depends(get_product_agent_service),
]
ReadingSelectionResolverDependency = Annotated[
    ReadingSelectionResolver,
    Depends(get_reading_selection_resolver),
]
ResearchNoteServiceDependency = Annotated[
    ResearchNoteService,
    Depends(get_research_note_service),
]
TranslationServiceDependency = Annotated[
    TranslationService,
    Depends(get_translation_service),
]
AgentTraceStoreDependency = Annotated[
    AgentTraceStoreService | None,
    Depends(get_agent_trace_store_service),
]
ConversationStoreDependency = Annotated[
    ConversationStoreService,
    Depends(get_conversation_store_service),
]
ConversationOwnershipDependency = Annotated[
    CompanionConversationOwnershipService,
    Depends(get_companion_ownership_service),
]


def get_agent_conversation_service(
    store: ConversationStoreDependency,
    ownership: ConversationOwnershipDependency,
) -> AgentConversationService:
    return AgentConversationService(store=store, ownership=ownership)


AgentConversationServiceDependency = Annotated[
    AgentConversationService,
    Depends(get_agent_conversation_service),
]


def get_agent_runtime(
    service: ProductAgentServiceDependency,
    resolver: ReadingSelectionResolverDependency,
    conversation_service: AgentConversationServiceDependency = None,
    research_service: ResearchNoteServiceDependency = None,
    translation_service: TranslationServiceDependency = None,
    trace_store: AgentTraceStoreDependency = None,
) -> AgentRuntime:
    """Build one request-scoped canonical Agent Runtime.

    Multi-agent collaboration is an advisory pre-workflow stage inside the same
    reliability/telemetry boundary. Stage 5.9 backs Research and Translation
    specialists with the existing production services, while Reading consumes
    the frozen document/knowledge context. ReadingAgentGraph remains authoritative
    for tools, confirmation, ReAct, evidence, grounding, synthesis, and response.
    """

    adapter = ProductAgentRuntimeAdapter(
        service,
        conversation_service=conversation_service,
    )
    graph = ReadingAgentGraph(adapter)
    collaboration_service = MultiAgentWorkspaceService(
        research_service=research_service,
        translation_service=translation_service,
    )
    return AgentRuntime(
        context_provider=ReadingContextProvider(resolver),
        collaboration_adapter=MultiAgentRuntimeBridge(collaboration_service),
        workflow_adapter=graph,
        run_recorder=trace_store.record if trace_store is not None else None,
    )


__all__ = ["get_agent_conversation_service", "get_agent_runtime"]
