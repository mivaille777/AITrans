import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.tools import get_tool_management_service, router
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.tool_management_repository import ToolManagementRepository
from backend.services.tool_management_service import ToolManagementService
from backend.services.tool_policy_service import ToolPolicyService


def setup(tmp_path):
    policy = ToolPolicyService(ToolManagementRepository(tmp_path / "tools.sqlite3"))
    registry = AgentToolRegistry(tool_policy=policy)
    service = ToolManagementService(registry, policy)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tool_management_service] = lambda: service
    return policy, registry, service, TestClient(app)


def test_policy_persists_rejects_stale_revision_and_keeps_disabled_in_management(
    tmp_path,
):
    policy, registry, service, client = setup(tmp_path)
    tool = service.detail("builtin:inspect_reading_context")
    response = client.patch(
        "/api/tools/" + tool.tool_id, json={"revision": tool.revision, "enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert (
        client.patch(
            "/api/tools/" + tool.tool_id,
            json={"revision": tool.revision, "enabled": True},
        ).status_code
        == 409
    )
    assert not any(x.name == tool.name for x in registry.list_tools())
    assert service.list(status="disabled").matched_total == 1
    with pytest.raises(PermissionError, match="disabled"):
        registry.execute(tool.name, source_text="text")
    restarted = ToolPolicyService(ToolManagementRepository(policy.repository.path))
    assert not restarted.is_enabled(tool.name)
    latest = service.detail(tool.tool_id)
    assert (
        client.patch(
            "/api/tools/" + tool.tool_id,
            json={"revision": latest.revision, "enabled": True},
        ).status_code
        == 200
    )
    assert registry.execute(tool.name, source_text="text").tool_name == tool.name


def test_all_disabled_stays_empty_and_native_full_read_cannot_bypass(tmp_path):
    policy, registry, service, _ = setup(tmp_path)
    for item in registry.list_all_tools():
        policy.update("builtin:" + item.name, 0, False)
    assert registry.list_tools() == ()
    assert service.list().disabled == service.list().total
    from backend.agent_tools.base import AgentToolInvocationContext
    from backend.agent_tools.knowledge import KnowledgeAgentTools, KnowledgeSearchArgs

    tools = KnowledgeAgentTools(retrieval_service=None, tool_policy=policy)
    context = AgentToolInvocationContext(knowledge_document_ids=["doc"])
    with pytest.raises(PermissionError, match="disabled"):
        tools.search_knowledge_base(context, KnowledgeSearchArgs(query="agent"))
    policy.repository.update("builtin:read_knowledge_chunk", 0, enabled=False)
    with pytest.raises(PermissionError, match="disabled"):
        tools.read_document_batch(context, [])


def test_automatic_explicit_native_and_legacy_entry_points_share_policy(tmp_path):
    from types import SimpleNamespace

    from backend.agent_core.exceptions import AgentRuntimeError
    from backend.api.agent import router as agent_router
    from backend.api.dependencies import get_agent_tool_registry
    from backend.models.knowledge_access import KnowledgeAccessPolicy
    from backend.services.knowledge_function_recovery import KnowledgeFunctionRun
    from backend.services.product_agent_service import ProductAgentService

    policy, registry, _service, _ = setup(tmp_path)
    policy.update("builtin:inspect_reading_context", 0, False)
    agent = object.__new__(ProductAgentService)
    agent._registry = registry
    assert "inspect_reading_context" not in {
        item.name for item in agent._tools_for_payload({})
    }
    with pytest.raises(AgentRuntimeError):
        agent._tools_for_payload({"enabled_tools": ["inspect_reading_context"]})
    policy.update("builtin:search_knowledge_base", 0, False)
    native = object.__new__(KnowledgeFunctionRun)
    native.state = SimpleNamespace(policy=KnowledgeAccessPolicy.AUTO)
    native.searches = native.reads = native.total = 0
    native.tool_policy = policy
    assert "search_knowledge_base" not in native.available()
    from backend.services.companion_chat_service import CompanionChatService

    companion = object.__new__(CompanionChatService)
    companion._tool_policy = policy
    assert companion.prepare_knowledge("query").fallback_reason == "tool_disabled:search_knowledge_base"
    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_agent_tool_registry] = lambda: registry
    client = TestClient(app)
    assert (
        client.post(
            "/api/agent/tools/inspect_reading_context/execute",
            json={"source_text": "text"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/agent/tools/save_research_note/execute", json={"source_text": "text"}
        ).status_code
        == 403
    )


def test_concurrent_configuration_writer_cannot_overwrite_stale_state(tmp_path):
    first, _, _, _ = setup(tmp_path)
    second = ToolPolicyService(ToolManagementRepository(first.repository.path))
    first.update("builtin:inspect_reading_context", 0, False)
    from backend.services.tool_management_service import ToolManagementError

    with pytest.raises(ToolManagementError, match="changed"):
        second.update("builtin:inspect_reading_context", 0, True)
    assert not second.is_enabled("inspect_reading_context")
