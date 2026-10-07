from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.agent_core.reliability import AgentRunControl
from backend.agent_tools.base import AgentToolExecutionResult
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.models.tool_configuration import (
    CustomToolPreset,
    ToolImportDocument,
    ToolImportRequest,
)
from backend.models.tool_management import ToolUpdate
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.product_agent_service import ProductAgentService
from backend.services.tool_custom_service import ToolCustomService
from backend.services.tool_management_repository import ToolManagementRepository
from backend.services.tool_management_service import (
    ToolManagementError,
    ToolManagementService,
)
from backend.services.tool_policy_service import ToolPolicyService


def setup(tmp_path):
    policy = ToolPolicyService(ToolManagementRepository(tmp_path / "config.sqlite3"))
    registry = AgentToolRegistry(tool_policy=policy, retrieval_service=object())
    management = ToolManagementService(registry, policy)
    return ToolCustomService(management), registry, policy


def preset(name="custom_research_search", **values):
    return CustomToolPreset(
        **{
            "name": name,
            "title": "Research search",
            "fixed_arguments": {"top_k": 3},
            "exposed_fields": ["query", "document_ids", "document_scope"],
            **values,
        }
    )


def test_custom_tool_executes_through_agent_with_scope_budget_and_primitive_policy(
    tmp_path,
):
    service, registry, policy = setup(tmp_path)
    calls = []
    primitive = registry.get_definition("search_knowledge_base")

    def execute(context, args):
        calls.append((context, args))
        return AgentToolExecutionResult(
            tool_name="search_knowledge_base",
            output_text="searched",
            effect="read",
            data={
                "query": args.query,
                "retrieval_strategy": "hybrid",
                "results": [],
                "elapsed_ms": 0,
            },
        )

    registry._definition_by_name[primitive.spec.name] = replace(
        primitive, executor=execute
    )
    created = service.create(preset())
    assert created.origin == "custom" and not created.enabled
    assert "top_k" not in created.input_schema["properties"]
    assert created.execution_capabilities["supports_native_chat"] is False
    assert created.name not in {x.name for x in registry.list_tools()}
    enabled = service.management.update(
        created.tool_id, ToolUpdate(revision=created.revision, enabled=True)
    )
    agent = ProductAgentService(registry=registry, chat_service=SimpleNamespace())
    control = AgentRunControl()
    result, waiting = agent._execute_tool(
        plan=AgentPlan(
            action="tool", tool_name=created.name, arguments={"query": "agent"}
        ),
        route=AgentRouteDecision(),
        reading={},
        payload={
            "enabled_tools": [created.name],
            "knowledge_document_ids": ["doc"],
            "trace_id": "trace",
        },
        control=control,
        event_sink=None,
        request_id=1,
    )
    assert not waiting and result.tool_name == created.name
    assert calls[0][0].knowledge_document_ids == ["doc"]
    assert calls[0][1].top_k == 3
    assert control.knowledge_search_count == 1
    with pytest.raises(ValueError, match="Fixed"):
        registry.execute(
            created.name, query="agent", top_k=50, knowledge_document_ids=["doc"]
        )
    policy.update("builtin:search_knowledge_base", 0, False)
    assert not service.management.detail(enabled.tool_id).effective_enabled
    with pytest.raises(PermissionError):
        registry.execute(created.name, query="agent", knowledge_document_ids=["doc"])


def test_configuration_validation_and_builtin_immutable_authority(tmp_path):
    service, registry, _ = setup(tmp_path)
    for invalid in [
        preset(fixed_arguments={"top_k": 999}),
        preset(exposed_fields=["query", "top_k"]),
        preset(exposed_fields=["top_k"], fixed_arguments={}),
        preset(timeout_seconds=120),
    ]:
        with pytest.raises(ToolManagementError):
            service.create(invalid)
    with pytest.raises(ValidationError):
        CustomToolPreset.model_validate(
            {"name": "custom_test", "title": "Test", "executor": "python"}
        )
    tool = service.management.detail("builtin:search_knowledge_base")
    edited = service.management.update(
        tool.tool_id,
        ToolUpdate(
            revision=tool.revision,
            config={
                "description": "Search documents",
                "defaults": {"top_k": 3},
                "timeout_seconds": 10,
            },
        ),
    )
    assert edited.description == "Search documents"
    assert registry.get_definition(tool.name).parse_args({"query": "agent"}).top_k == 3
    assert edited.permissions == tool.permissions and edited.effect == tool.effect
    custom = service.create(preset())
    assert custom.limits["timeout_seconds"] == 10
    with pytest.raises(ToolManagementError):
        service.management.update(
            tool.tool_id,
            ToolUpdate(revision=edited.revision, config={"effect": "write"}),
        )


def test_import_preview_conflicts_atomic_rollback_and_stale_token(tmp_path):
    service, _, _ = setup(tmp_path)
    existing = service.create(preset())
    document = ToolImportDocument(tools=[preset("custom_second_search"), preset()])
    preview = service.preview(document)
    assert preview["conflicts"][0]["name"] == existing.name
    with pytest.raises(ToolManagementError, match="conflicting"):
        service.apply(
            ToolImportRequest(document=document, preview_token=preview["preview_token"])
        )
    assert service.repository.custom("custom_second_search") is None
    replaced = service.apply(
        ToolImportRequest(
            document=document,
            preview_token=preview["preview_token"],
            conflict_mode="replace",
        )
    )
    assert len(replaced["items"]) == 2 and all(
        not x["enabled"] for x in replaced["items"]
    )
    with pytest.raises(ToolManagementError, match="changed"):
        service.apply(
            ToolImportRequest(
                document=document,
                preview_token=preview["preview_token"],
                conflict_mode="replace",
            )
        )
    with pytest.raises(ToolManagementError, match="schema_version"):
        service.preview(ToolImportDocument(schema_version=2, tools=[preset()]))


def test_archive_blocks_calls_and_preserves_identity_for_history(tmp_path):
    service, registry, _ = setup(tmp_path)
    tool = service.create(preset())
    archived = service.archive(tool.tool_id, tool.revision)
    assert archived.archived and not archived.enabled
    assert tool.name not in {x.name for x in registry.list_all_tools()}
    with pytest.raises(PermissionError):
        registry.execute(tool.name, query="agent")
    with pytest.raises(ToolManagementError):
        service.create(preset())
    assert service.management.detail(tool.tool_id).tool_id == tool.tool_id
