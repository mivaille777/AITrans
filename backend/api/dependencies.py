from __future__ import annotations

import os
from threading import Lock

from backend.api.knowledge_dependencies import (
    get_knowledge_library_service,
    get_rag_runtime,
    get_retrieval_service,
)
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.api.llm_dependencies import (
    build_rag_query_planner,
    build_routed_product_agent_service,
    build_routed_quick_action_service,
)
from backend.sandbox.docker_runtime import DEFAULT_IMAGE, DockerSandboxRuntime
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxRuntimeHealth
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.browser_context_service import BrowserContextService
from backend.services.companion_chat_service import CompanionChatService
from backend.services.companion_handoff_service import CompanionHandoffService
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.services.companion_query_router import CompanionQueryRouter
from backend.services.conversation_lifecycle_service import ConversationLifecycleService
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.overlay_state_service import OverlayStateService
from backend.services.product_agent_service import ProductAgentService
from backend.services.quick_action_service import QuickActionService
from backend.services.rag_debug_service import RagDebugService
from backend.services.rag_debug_store_service import RagDebugStoreService
from backend.services.reading_selection_resolver import ReadingSelectionResolver
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.sandbox_debug_service import SandboxDebugService
from backend.services.translation_service import TranslationService

_translation_service: TranslationService | None = None
_translation_service_lock = Lock()
_browser_context_service: BrowserContextService | None = None
_browser_context_service_lock = Lock()
_reading_selection_resolver: ReadingSelectionResolver | None = None
_reading_selection_resolver_lock = Lock()
_overlay_state_service: OverlayStateService | None = None
_overlay_state_service_lock = Lock()
_quick_action_service: QuickActionService | None = None
_quick_action_service_lock = Lock()
_research_workspace_service: ResearchWorkspaceService | None = None
_research_workspace_service_lock = Lock()
_research_note_service: ResearchNoteService | None = None
_research_note_service_lock = Lock()
_companion_handoff_service: CompanionHandoffService | None = None
_companion_handoff_service_lock = Lock()
_companion_chat_service: CompanionChatService | None = None
_companion_chat_service_lock = Lock()
_conversation_store_service: ConversationStoreService | None = None
_conversation_store_service_lock = Lock()
_companion_ownership_service: CompanionConversationOwnershipService | None = None
_companion_ownership_service_lock = Lock()
_agent_tool_registry: AgentToolRegistry | None = None
_agent_tool_registry_lock = Lock()
_sandbox_manager: SandboxManager | None = None
_sandbox_manager_lock = Lock()
_filesystem_workspace_service: FilesystemWorkspaceService | None = None
_filesystem_workspace_service_lock = Lock()
_sandbox_debug_service: SandboxDebugService | None = None
_sandbox_debug_service_lock = Lock()
_sandbox_approval_service: SandboxApprovalService | None = None
_sandbox_approval_service_lock = Lock()
_product_agent_service: ProductAgentService | None = None
_product_agent_service_lock = Lock()
_rag_debug_store_service: RagDebugStoreService | None = None
_rag_debug_store_service_lock = Lock()
_rag_debug_service: RagDebugService | None = None
_rag_debug_service_lock = Lock()


def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is not None:
        return _translation_service
    with _translation_service_lock:
        if _translation_service is None:
            _translation_service = TranslationService()
        return _translation_service


def close_translation_service() -> None:
    global _translation_service
    with _translation_service_lock:
        service = _translation_service
        _translation_service = None
    if service is not None:
        service.close()


def get_browser_context_service() -> BrowserContextService:
    global _browser_context_service
    if _browser_context_service is not None:
        return _browser_context_service
    with _browser_context_service_lock:
        if _browser_context_service is None:
            _browser_context_service = BrowserContextService()
        return _browser_context_service


def close_browser_context_service() -> None:
    global _browser_context_service
    with _browser_context_service_lock:
        service = _browser_context_service
        _browser_context_service = None
    if service is not None:
        service.close()


def get_reading_selection_resolver() -> ReadingSelectionResolver:
    global _reading_selection_resolver
    if _reading_selection_resolver is not None:
        return _reading_selection_resolver
    with _reading_selection_resolver_lock:
        if _reading_selection_resolver is None:
            _reading_selection_resolver = ReadingSelectionResolver(
                browser_context_service=get_browser_context_service()
            )
        return _reading_selection_resolver


def close_reading_selection_resolver() -> None:
    global _reading_selection_resolver
    with _reading_selection_resolver_lock:
        resolver = _reading_selection_resolver
        _reading_selection_resolver = None
    if resolver is not None:
        resolver.clear_cache()


def get_overlay_state_service() -> OverlayStateService:
    global _overlay_state_service
    if _overlay_state_service is not None:
        return _overlay_state_service
    with _overlay_state_service_lock:
        if _overlay_state_service is None:
            _overlay_state_service = OverlayStateService()
        return _overlay_state_service


def get_quick_action_service() -> QuickActionService:
    global _quick_action_service
    if _quick_action_service is not None:
        return _quick_action_service
    with _quick_action_service_lock:
        if _quick_action_service is None:
            _quick_action_service = build_routed_quick_action_service()
        return _quick_action_service


def close_quick_action_service() -> None:
    global _quick_action_service
    with _quick_action_service_lock:
        service = _quick_action_service
        _quick_action_service = None
    if service is not None:
        service.close()


def get_research_workspace_service() -> ResearchWorkspaceService:
    global _research_workspace_service
    if _research_workspace_service is not None:
        return _research_workspace_service
    with _research_workspace_service_lock:
        if _research_workspace_service is None:
            _research_workspace_service = ResearchWorkspaceService()
        return _research_workspace_service


def close_research_workspace_service() -> None:
    global _research_workspace_service
    with _research_workspace_service_lock:
        _research_workspace_service = None


def get_research_note_service() -> ResearchNoteService:
    global _research_note_service
    if _research_note_service is not None:
        return _research_note_service
    with _research_note_service_lock:
        if _research_note_service is None:
            _research_note_service = ResearchNoteService(
                reading_resolver=get_reading_selection_resolver(),
                workspace_service=get_research_workspace_service(),
            )
        return _research_note_service


def get_companion_handoff_service() -> CompanionHandoffService:
    global _companion_handoff_service
    if _companion_handoff_service is not None:
        return _companion_handoff_service
    with _companion_handoff_service_lock:
        if _companion_handoff_service is None:
            _companion_handoff_service = CompanionHandoffService(
                reading_resolver=get_reading_selection_resolver()
            )
        return _companion_handoff_service


def get_companion_chat_service() -> CompanionChatService:
    global _companion_chat_service
    if _companion_chat_service is not None:
        return _companion_chat_service
    with _companion_chat_service_lock:
        if _companion_chat_service is None:
            _companion_chat_service = CompanionChatService(
                query_router=CompanionQueryRouter(),
                reading_resolver_factory=get_reading_selection_resolver,
                retrieval_service_factory=get_retrieval_service,
                query_planner_factory=build_rag_query_planner,
                knowledge_library_service_factory=get_knowledge_library_service,
            )
        return _companion_chat_service


def close_companion_chat_service() -> None:
    global _companion_chat_service
    with _companion_chat_service_lock:
        service = _companion_chat_service
        _companion_chat_service = None
    if service is not None:
        service.close()


def get_conversation_store_service() -> ConversationStoreService:
    global _conversation_store_service
    if _conversation_store_service is not None:
        return _conversation_store_service
    with _conversation_store_service_lock:
        if _conversation_store_service is None:
            _conversation_store_service = ConversationLifecycleService()
        return _conversation_store_service


def close_conversation_store_service() -> None:
    global _conversation_store_service
    with _conversation_store_service_lock:
        _conversation_store_service = None


def get_companion_ownership_service() -> CompanionConversationOwnershipService:
    global _companion_ownership_service
    if _companion_ownership_service is not None:
        return _companion_ownership_service
    with _companion_ownership_service_lock:
        if _companion_ownership_service is None:
            _companion_ownership_service = CompanionConversationOwnershipService()
        return _companion_ownership_service


def close_companion_ownership_service() -> None:
    global _companion_ownership_service
    with _companion_ownership_service_lock:
        service = _companion_ownership_service
        _companion_ownership_service = None
    if service is not None:
        service.clear()


def get_agent_tool_registry() -> AgentToolRegistry:
    global _agent_tool_registry
    if _agent_tool_registry is not None:
        return _agent_tool_registry
    with _agent_tool_registry_lock:
        if _agent_tool_registry is None:
            # Local imports avoid module cycles: research-memory and ledger
            # dependencies reuse the Note/Workspace singletons defined here.
            from backend.api.evidence_ledger_dependencies import (
                get_evidence_ledger_service,
            )
            from backend.api.research_memory_dependencies import (
                get_research_memory_service,
            )
            from backend.services.cross_document_research_service import (
                CrossDocumentResearchService,
            )

            research_note_service = get_research_note_service()
            research_memory_service = get_research_memory_service()
            cross_document_service = CrossDocumentResearchService(
                research_memory_service=research_memory_service,
                research_note_service=research_note_service,
            )
            rag_runtime = get_rag_runtime()
            _agent_tool_registry = AgentToolRegistry(
                translation_service=get_translation_service(),
                quick_action_service=get_quick_action_service(),
                research_note_service=research_note_service,
                research_memory_service=research_memory_service,
                cross_document_research_service=cross_document_service,
                evidence_ledger_service=get_evidence_ledger_service(),
                retrieval_service=rag_runtime.retrieval_service,
                query_planner=build_rag_query_planner(),
                chunk_store=rag_runtime.sparse_retriever,
                jit_search_read_enabled=rag_runtime.config.jit_search_read_enabled,
                knowledge_workspace_service=get_knowledge_workspace_service(),
                sandbox_manager=get_sandbox_manager(),
                filesystem_workspace_service=get_filesystem_workspace_service(),
                sandbox_debug_service=get_sandbox_debug_service(),
            )
        return _agent_tool_registry


def _sandbox_enabled() -> bool:
    value = os.getenv("AITRANS_SANDBOX_ENABLED", "false").strip().casefold()
    return value in {"1", "true", "yes", "on"}


def get_filesystem_workspace_service() -> FilesystemWorkspaceService:
    global _filesystem_workspace_service
    if _filesystem_workspace_service is not None:
        return _filesystem_workspace_service
    with _filesystem_workspace_service_lock:
        if _filesystem_workspace_service is None:
            _filesystem_workspace_service = FilesystemWorkspaceService()
        return _filesystem_workspace_service


def close_filesystem_workspace_service() -> None:
    global _filesystem_workspace_service
    with _filesystem_workspace_service_lock:
        _filesystem_workspace_service = None


def get_sandbox_debug_service() -> SandboxDebugService:
    global _sandbox_debug_service
    if _sandbox_debug_service is not None:
        return _sandbox_debug_service
    with _sandbox_debug_service_lock:
        if _sandbox_debug_service is None:
            _sandbox_debug_service = SandboxDebugService()
        return _sandbox_debug_service


def close_sandbox_debug_service() -> None:
    global _sandbox_debug_service
    with _sandbox_debug_service_lock:
        service = _sandbox_debug_service
        _sandbox_debug_service = None
    if service is not None:
        service.close()


def get_sandbox_approval_service() -> SandboxApprovalService:
    global _sandbox_approval_service
    if _sandbox_approval_service is not None:
        return _sandbox_approval_service
    with _sandbox_approval_service_lock:
        if _sandbox_approval_service is None:
            _sandbox_approval_service = SandboxApprovalService()
        return _sandbox_approval_service


def close_sandbox_approval_service() -> None:
    global _sandbox_approval_service
    with _sandbox_approval_service_lock:
        service = _sandbox_approval_service
        _sandbox_approval_service = None
    if service is not None:
        service.close()


def get_sandbox_runtime_health() -> SandboxRuntimeHealth:
    if not _sandbox_enabled():
        return SandboxRuntimeHealth(
            available=False,
            image=os.getenv("AITRANS_SANDBOX_IMAGE", DEFAULT_IMAGE).strip()
            or DEFAULT_IMAGE,
            error_code="sandbox_disabled",
            message="Sandbox execution is disabled.",
        )
    manager = _sandbox_manager
    if manager is not None:
        return manager.health()
    image = os.getenv("AITRANS_SANDBOX_IMAGE", DEFAULT_IMAGE).strip() or DEFAULT_IMAGE
    try:
        runtime = DockerSandboxRuntime(image=image)
    except ValueError:
        return SandboxRuntimeHealth(
            available=False,
            image=image,
            error_code="invalid_sandbox_image",
            message="The configured sandbox image is invalid.",
        )
    try:
        return runtime.health()
    finally:
        runtime.close()


def get_sandbox_manager() -> SandboxManager | None:
    """Return a ready sandbox only when explicitly enabled and healthy."""

    global _sandbox_manager
    if not _sandbox_enabled():
        return None
    if _sandbox_manager is not None:
        return _sandbox_manager
    with _sandbox_manager_lock:
        if _sandbox_manager is None:
            image = os.getenv("AITRANS_SANDBOX_IMAGE", DEFAULT_IMAGE).strip()
            try:
                runtime = DockerSandboxRuntime(image=image or DEFAULT_IMAGE)
            except ValueError:
                return None
            health = runtime.health()
            if not health.available:
                runtime.close()
                return None
            _sandbox_manager = SandboxManager(runtime)
        return _sandbox_manager


def close_sandbox_manager() -> None:
    global _sandbox_manager
    with _sandbox_manager_lock:
        manager = _sandbox_manager
        _sandbox_manager = None
    if manager is not None:
        manager.close()


def close_agent_tool_registry() -> None:
    global _agent_tool_registry
    with _agent_tool_registry_lock:
        _agent_tool_registry = None


def get_product_agent_service() -> ProductAgentService:
    global _product_agent_service
    if _product_agent_service is not None:
        return _product_agent_service
    with _product_agent_service_lock:
        if _product_agent_service is None:
            _product_agent_service = build_routed_product_agent_service(
                registry=get_agent_tool_registry(),
                resolver=get_reading_selection_resolver(),
            )
        return _product_agent_service


def close_product_agent_service() -> None:
    global _product_agent_service
    with _product_agent_service_lock:
        service = _product_agent_service
        _product_agent_service = None
    if service is not None:
        service.close()


def get_rag_debug_store_service() -> RagDebugStoreService:
    global _rag_debug_store_service
    if _rag_debug_store_service is not None:
        return _rag_debug_store_service
    with _rag_debug_store_service_lock:
        if _rag_debug_store_service is None:
            _rag_debug_store_service = RagDebugStoreService()
        return _rag_debug_store_service


def get_rag_debug_service() -> RagDebugService:
    global _rag_debug_service
    if _rag_debug_service is not None:
        return _rag_debug_service
    with _rag_debug_service_lock:
        if _rag_debug_service is None:
            _rag_debug_service = RagDebugService(store=get_rag_debug_store_service())
        return _rag_debug_service


def close_rag_debug_service() -> None:
    global _rag_debug_service
    with _rag_debug_service_lock:
        service = _rag_debug_service
        _rag_debug_service = None
    if service is not None:
        service.close()
