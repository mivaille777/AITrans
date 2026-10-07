from __future__ import annotations

from unittest.mock import Mock

import pytest

from backend.api import llm_dependencies


class _FakeTextService:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class _FakeGateway:
    def __init__(self, text_service: _FakeTextService) -> None:
        self.text_service = text_service
        self.created_roles: list[str] = []

    def create_text_service(self, role: str) -> _FakeTextService:
        self.created_roles.append(role)
        return self.text_service


def test_planner_text_service_is_created_lazily_and_cached(monkeypatch) -> None:
    text_service = _FakeTextService()
    gateway = _FakeGateway(text_service)
    monkeypatch.setattr(llm_dependencies, "_gateway", gateway)
    monkeypatch.setattr(llm_dependencies, "_planner_text_service", None)

    first = llm_dependencies.get_planner_text_service()
    second = llm_dependencies.get_planner_text_service()
    planner = llm_dependencies.build_rag_query_planner()

    assert first is second is text_service
    assert planner._text_service is text_service
    assert gateway.created_roles == ["planner"]


def test_reset_releases_cached_planner_and_gateway(monkeypatch) -> None:
    text_service = _FakeTextService()
    gateway = _FakeGateway(text_service)
    monkeypatch.setattr(llm_dependencies, "_gateway", gateway)
    monkeypatch.setattr(llm_dependencies, "_planner_text_service", text_service)

    llm_dependencies.reset_llm_dependencies()

    assert text_service.close_count == 1
    assert llm_dependencies._gateway is None
    assert llm_dependencies._planner_text_service is None
    assert gateway.created_roles == []


@pytest.mark.parametrize("rewrite_enabled", [False, True])
def test_agent_registry_respects_optional_rag_rewrite(monkeypatch, rewrite_enabled):
    from backend.api import (
        dependencies,
        evidence_ledger_dependencies,
        research_memory_dependencies,
    )

    monkeypatch.setattr(dependencies, "_agent_tool_registry", None)
    runtime = Mock()
    runtime.config.query_rewrite_enabled = rewrite_enabled
    monkeypatch.setattr(dependencies, "get_rag_runtime", lambda: runtime)
    for name in (
        "get_tool_policy_service",
        "get_translation_service",
        "get_quick_action_service",
        "get_research_note_service",
        "get_knowledge_library_service",
        "get_knowledge_workspace_service",
        "get_sandbox_manager",
        "get_filesystem_workspace_service",
        "get_sandbox_debug_service",
        "get_sandbox_approval_service",
    ):
        monkeypatch.setattr(dependencies, name, Mock())
    monkeypatch.setattr(
        research_memory_dependencies, "get_research_memory_service", Mock()
    )
    monkeypatch.setattr(
        evidence_ledger_dependencies, "get_evidence_ledger_service", Mock()
    )
    planner_factory = Mock()
    registry_factory = Mock()
    monkeypatch.setattr(dependencies, "build_rag_query_planner", planner_factory)
    monkeypatch.setattr(dependencies, "AgentToolRegistry", registry_factory)
    dependencies.get_agent_tool_registry()
    assert planner_factory.call_count == int(rewrite_enabled)
    assert registry_factory.call_args.kwargs["query_planner"] is (
        planner_factory.return_value if rewrite_enabled else None
    )
