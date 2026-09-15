from __future__ import annotations

import pytest

import backend.services.agent_multi_step_planner_service as multi_step_module
import backend.services.agent_planner_service as planner_module
import backend.services.agent_react_decision_service as react_decision_module
from backend.services.agent_multi_step_planner_service import AgentMultiStepPlannerService
from backend.services.agent_planner_service import AgentPlannerService
from backend.services.agent_react_decision_service import AgentReActDecisionService
from backend.services.agent_router_service import AgentSemanticRouterService
from backend.services.product_agent_service import ProductAgentService


class _Registry:
    def list_tools(self):
        return ()


class _Chat:
    pass


def _unexpected_ai_text_service() -> None:
    raise AssertionError("AITextService must stay lazy until an LLM operation is requested")


def test_single_step_planner_does_not_create_ai_provider_at_construction(monkeypatch) -> None:
    monkeypatch.setattr(planner_module, "AITextService", _unexpected_ai_text_service)

    planner = AgentPlannerService()

    assert planner.provider_name == "unknown"
    assert planner.model == "unknown"
    with pytest.raises(AssertionError, match="must stay lazy"):
        planner._get_text_service()


def test_multi_step_planner_does_not_create_ai_provider_at_construction(monkeypatch) -> None:
    monkeypatch.setattr(multi_step_module, "AITextService", _unexpected_ai_text_service)

    planner = AgentMultiStepPlannerService()

    assert planner.provider_name == "unknown"
    assert planner.model == "unknown"
    with pytest.raises(AssertionError, match="must stay lazy"):
        planner._get_text_service()


def test_react_decision_service_does_not_create_ai_provider_at_construction(monkeypatch) -> None:
    monkeypatch.setattr(react_decision_module, "AITextService", _unexpected_ai_text_service)

    service = AgentReActDecisionService()

    assert service.provider_name == "unknown"
    assert service.model == "unknown"
    with pytest.raises(AssertionError, match="must stay lazy"):
        service._get_text_service()


def test_semantic_router_can_be_created_without_initializing_ai_provider(monkeypatch) -> None:
    monkeypatch.setattr(planner_module, "AITextService", _unexpected_ai_text_service)

    router = AgentSemanticRouterService()

    assert router.provider_name == "unknown"
    assert router.model == "unknown"


def test_product_agent_can_be_created_without_api_credentials(monkeypatch) -> None:
    monkeypatch.setattr(planner_module, "AITextService", _unexpected_ai_text_service)
    monkeypatch.setattr(multi_step_module, "AITextService", _unexpected_ai_text_service)

    service = ProductAgentService(
        registry=_Registry(),  # type: ignore[arg-type]
        chat_service=_Chat(),  # type: ignore[arg-type]
    )

    assert service is not None
    service.close()
