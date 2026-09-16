from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from backend.agent_core.context import ReadingContextProvider
from backend.agent_core.orchestration import (
    AuthoritativeScopeResolver,
    ScopedEvidenceService,
    build_artifact_store,
)
from backend.agent_core.orchestration.serial_executor import (
    LegacySpecialistExecutor,
    SerialTaskGraphExecutor,
)
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_graph.document_analyst_graph import DocumentAnalystGraph
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.agent_graph.research_synthesizer_graph import ResearchSynthesizerGraph
from backend.api.agent_checkpoint_dependencies import get_agent_checkpoint_service
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.api.dependencies import (
    get_companion_ownership_service,
    get_conversation_store_service,
    get_product_agent_service,
    get_reading_selection_resolver,
    get_research_note_service,
    get_research_workspace_service,
    get_retrieval_service,
    get_translation_service,
)
from backend.api.evidence_review_dependencies import get_evidence_review_service
from backend.api.knowledge_board_dependencies import get_knowledge_board_service
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.models.agent_tasks import TaskRole
from backend.services.agent_checkpoint_service import AgentCheckpointService
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
from backend.services.research_orchestration_service import ResearchOrchestrationService
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
ResearchWorkspaceDependency = Annotated[
    object,
    Depends(get_research_workspace_service),
]
KnowledgeWorkspaceDependency = Annotated[
    object,
    Depends(get_knowledge_workspace_service),
]
KnowledgeBoardDependency = Annotated[
    object,
    Depends(get_knowledge_board_service),
]


class _LazyRetrievalService:
    """Avoid opening the process-wide Qdrant store for non-retrieval Agent runs."""

    @staticmethod
    def retrieve(*args, **kwargs):
        return get_retrieval_service().retrieve(*args, **kwargs)


class _LazyEvidenceReviewService:
    @staticmethod
    def snapshot(*args, **kwargs):
        return get_evidence_review_service().snapshot(*args, **kwargs)


AgentTraceStoreDependency = Annotated[
    AgentTraceStoreService | None,
    Depends(get_agent_trace_store_service),
]
AgentCheckpointDependency = Annotated[
    AgentCheckpointService | None,
    Depends(get_agent_checkpoint_service),
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
    checkpoint_service: AgentCheckpointDependency = None,
    research_workspace: ResearchWorkspaceDependency = None,
    knowledge_workspace: KnowledgeWorkspaceDependency = None,
    knowledge_boards: KnowledgeBoardDependency = None,
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
    collaboration_service = MultiAgentWorkspaceService(
        research_service=research_service,
        translation_service=translation_service,
    )
    scope_resolver = AuthoritativeScopeResolver(
        research_workspaces=research_workspace,
        knowledge_workspace=knowledge_workspace,
        knowledge_boards=knowledge_boards,
        research_notes=research_service,
    )
    evidence_service = ScopedEvidenceService(
        rag_retriever=_LazyRetrievalService(),
        research_notes=research_service,
        knowledge_workspace=knowledge_workspace,
    )
    compatibility_executor = LegacySpecialistExecutor(
        collaboration_service.registry,
        evidence_service=evidence_service,
    )
    artifact_store = build_artifact_store()
    document_analyst = DocumentAnalystGraph(
        evidence_service=evidence_service,
        artifact_store=artifact_store,
    )
    research_synthesizer = ResearchSynthesizerGraph(
        artifact_store=artifact_store,
        evidence_review_service=_LazyEvidenceReviewService(),
    )
    orchestration_service = ResearchOrchestrationService(
        scope_resolver=scope_resolver,
        executor=SerialTaskGraphExecutor(
            {
                TaskRole.DOCUMENT: document_analyst,
                TaskRole.RESEARCH: research_synthesizer,
                TaskRole.WRITER: compatibility_executor,
                TaskRole.CURATOR: compatibility_executor,
            }
        ),
    )
    collaboration_adapter = MultiAgentRuntimeBridge(
        collaboration_service,
        orchestrator=orchestration_service,
    )
    graph = ReadingAgentGraph(
        adapter,
        checkpointer=(
            checkpoint_service.checkpointer
            if checkpoint_service is not None
            else None
        ),
        context_provider=ReadingContextProvider(resolver),
        collaboration_adapter=collaboration_adapter,
    )
    return AgentRuntime(
        workflow_adapter=graph,
        run_recorder=trace_store.record if trace_store is not None else None,
    )


__all__ = ["get_agent_conversation_service", "get_agent_runtime"]
