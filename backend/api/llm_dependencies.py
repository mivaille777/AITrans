"""LLM gateway dependency and routed service factories."""

from __future__ import annotations

from threading import Lock

from app.ai.chat.service import AIChatService
from app.ai.gateway import LLMGateway, RoutedAITextService
from backend.rag.query_planner import RagQueryPlanner
from backend.services.agent_multi_step_planner_service import (
    AgentMultiStepPlannerService,
)
from backend.services.agent_router_service import AgentSemanticRouterService
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.companion_chat_service import CompanionChatService
from backend.services.grounded_synthesis_service import GroundedSynthesisService
from backend.services.product_agent_service import ProductAgentService
from backend.services.quick_action_service import QuickActionService
from backend.services.reading_selection_resolver import ReadingSelectionResolver

_gateway: LLMGateway | None = None
_gateway_lock = Lock()
_planner_text_service: RoutedAITextService | None = None
_planner_text_service_lock = Lock()


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is not None:
        return _gateway
    with _gateway_lock:
        if _gateway is None:
            _gateway = LLMGateway()
        return _gateway


def get_planner_text_service() -> RoutedAITextService:
    global _planner_text_service
    if _planner_text_service is not None:
        return _planner_text_service


def reset_llm_dependencies() -> None:
    """Release cached LLM clients after a local provider configuration update."""

    global _gateway, _planner_text_service
    with _planner_text_service_lock:
        planner_service = _planner_text_service
        _planner_text_service = None
    if planner_service is not None:
        planner_service.close()
    with _gateway_lock:
        _gateway = None
    with _planner_text_service_lock:
        if _planner_text_service is None:
            _planner_text_service = get_llm_gateway().create_text_service("planner")
        return _planner_text_service


def build_rag_query_planner() -> RagQueryPlanner:
    return RagQueryPlanner(text_service=get_planner_text_service())


def build_routed_quick_action_service() -> QuickActionService:
    gateway = get_llm_gateway()
    polish_service = gateway.create_text_service("polish")
    reading_service = gateway.create_text_service("reading")
    return QuickActionService(
        text_service=polish_service,
        chat_service=AIChatService(reading_service),
    )


def build_routed_product_agent_service(
    *,
    registry: AgentToolRegistry,
    resolver: ReadingSelectionResolver,
) -> ProductAgentService:
    gateway = get_llm_gateway()
    planner_text_service = get_planner_text_service()
    semantic_router = AgentSemanticRouterService(text_service=planner_text_service)
    multi_step_planner = AgentMultiStepPlannerService(
        text_service=planner_text_service
    )
    synthesis = CompanionChatService(
        text_service=gateway.create_text_service("agent_synthesis"),
        reading_resolver=resolver,
    )
    return ProductAgentService(
        registry=registry,
        chat_service=synthesis,
        grounded_synthesis_service=GroundedSynthesisService(chat_service=synthesis),
        semantic_router=semantic_router,
        multi_step_planner=multi_step_planner,
    )


__all__ = [
    "build_rag_query_planner",
    "build_routed_product_agent_service",
    "build_routed_quick_action_service",
    "get_llm_gateway",
    "get_planner_text_service",
    "reset_llm_dependencies",
]
