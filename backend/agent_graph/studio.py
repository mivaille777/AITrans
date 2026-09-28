from __future__ import annotations

from backend.agent_core.orchestration import (
    AuthoritativeScopeResolver,
    CoordinatorMemoryPort,
    InMemoryArtifactStore,
    ParallelTaskGraphExecutor,
    ScopedEvidenceService,
    ValidatedSupervisorPlanner,
    build_default_agent_registry,
)
from backend.agent_core.orchestration.migration import resolve_agent_graph_engine
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION
from backend.agent_graph.academic_writer_graph import AcademicWriterGraph
from backend.agent_graph.document_analyst_graph import DocumentAnalystGraph
from backend.agent_graph.knowledge_curator_graph import KnowledgeCuratorGraph
from backend.agent_graph.research_synthesizer_graph import ResearchSynthesizerGraph
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.api.dependencies import (
    get_companion_ownership_service,
    get_conversation_store_service,
    get_product_agent_service,
    get_research_note_service,
    get_research_workspace_service,
    get_retrieval_service,
)
from backend.api.evidence_review_dependencies import get_evidence_review_service
from backend.api.knowledge_board_dependencies import get_knowledge_board_service
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.api.memory_dependencies import get_memory_coordinator
from backend.models.agent_tasks import TaskRole
from backend.services.agent_conversation_service import AgentConversationService
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService
from backend.services.research_orchestration_service import ResearchOrchestrationService


class _LazyRetrievalService:
    @staticmethod
    def retrieve(*args, **kwargs):
        return get_retrieval_service().retrieve(*args, **kwargs)


class _LazyEvidenceReviewService:
    @staticmethod
    def snapshot(*args, **kwargs):
        return get_evidence_review_service().snapshot(*args, **kwargs)


class _LazyDependency:
    """Resolve Studio runtime services only when a graph node uses them."""

    def __init__(self, factory):
        self._factory = factory
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get_instance(), name)


def _build_conversation_service():
    return AgentConversationService(
        store=get_conversation_store_service(),
        ownership=get_companion_ownership_service(),
    )


def make_root_graph():
    """Build the production RootAgentGraph for LangSmith Studio.

    Agent Server graph factories may either accept no arguments or explicitly
    typed ``RunnableConfig`` / ``ServerRuntime`` parameters. Studio only needs
    the production topology here, so keep this factory argument-free and avoid
    ambiguous type-based injection during graph introspection.
    """

    adapter = ProductAgentRuntimeAdapter(
        _LazyDependency(get_product_agent_service),
        conversation_service=_LazyDependency(_build_conversation_service),
    )
    if resolve_agent_graph_engine() == "native":
        return _build_native_studio_graph(adapter).compiled_graph
    return RootAgentGraph(adapter).compiled_graph


def _build_native_studio_graph(adapter: ProductAgentRuntimeAdapter) -> RootAgentGraph:
    """Compile the same registered compiled specialist graphs used in production.

    This path is selected only when Studio is configured for native topology.
    In-memory artifacts avoid opening a user database during graph introspection;
    all service and data access remains lazy until a Studio run invokes a node.
    """

    artifacts = InMemoryArtifactStore()
    knowledge_workspace = _LazyDependency(get_knowledge_workspace_service)
    research_notes = _LazyDependency(get_research_note_service)
    evidence = ScopedEvidenceService(
        rag_retriever=_LazyRetrievalService(),
        research_notes=research_notes,
        knowledge_workspace=knowledge_workspace,
        evidence_review=_LazyEvidenceReviewService(),
    )
    document = DocumentAnalystGraph(
        evidence_service=evidence,
        artifact_store=artifacts,
    )
    research = ResearchSynthesizerGraph(
        artifact_store=artifacts,
        evidence_review_service=_LazyEvidenceReviewService(),
    )
    writer = AcademicWriterGraph(artifact_store=artifacts)
    curator = KnowledgeCuratorGraph(
        artifact_store=artifacts,
        knowledge_workspace=knowledge_workspace,
    )
    registry = build_default_agent_registry(
        graph_factories={
            "document": lambda: document,
            "research": lambda: research,
            "writer": lambda: writer,
            "curator": lambda: curator,
        }
    )
    specialists = {
        TaskRole.DOCUMENT: document,
        TaskRole.RESEARCH: research,
        TaskRole.WRITER: writer,
        TaskRole.CURATOR: curator,
    }
    executor = ParallelTaskGraphExecutor(specialists, artifact_store=artifacts)
    service = ResearchOrchestrationService(
        scope_resolver=AuthoritativeScopeResolver(
            research_workspaces=_LazyDependency(get_research_workspace_service),
            knowledge_workspace=knowledge_workspace,
            knowledge_boards=_LazyDependency(get_knowledge_board_service),
            research_notes=research_notes,
        ),
        planner=ValidatedSupervisorPlanner(agent_registry=registry),
        executor=executor,
        memory_port=CoordinatorMemoryPort(
            _LazyDependency(get_memory_coordinator),
            artifact_store=artifacts,
        ),
        temporary_executor=executor,
        artifact_store=artifacts,
    )
    return RootAgentGraph(
        adapter,
        orchestration_service=service,
        collaboration_adapter=MultiAgentRuntimeBridge(
            MultiAgentWorkspaceService(),
            orchestrator=service,
        ),
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )


def make_graph():
    """Keep the previous Studio factory path as a compatibility alias."""

    return make_root_graph()


__all__ = ["make_graph", "make_root_graph"]
