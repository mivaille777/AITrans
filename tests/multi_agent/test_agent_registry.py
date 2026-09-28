from __future__ import annotations

from dataclasses import replace

import pytest

from backend.agent_core.orchestration.agent_registry import (
    AgentRegistry,
    build_default_agent_registry,
)
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.orchestration.roles import RoleRegistry
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import ScopeContext, TaskRole


def test_four_existing_agents_share_planning_and_tool_policy_metadata() -> None:
    registry = build_default_agent_registry()
    planner = ValidatedSupervisorPlanner(agent_registry=registry)
    roles = RoleRegistry(agent_registry=registry)
    scope = ScopeContext.issue(scope_revision="lg01", allowed_document_ids=["paper-a"])

    assert [spec.agent_id for spec in planner.available_agents()] == [
        "curator", "document", "research", "writer",
    ]
    for role in TaskRole:
        spec = registry.for_role(role)
        assert registry.agent_id_for_role(role) == spec.agent_id
        assert spec.retry_policy.max_retries == 1
        assert spec.timeout_policy.seconds == 90.0
        assert roles.get(role).allowed_tools == spec.allowed_tools
        plan = planner.plan(
            route=OrchestrationRoute(
                lane=OrchestrationLane.SINGLE,
                primary_role=role,
                reason_code="lg01-test",
            ),
            objective="Analyze the paper",
            scope=scope,
        )
        assert plan is not None
        assert plan.tasks[0].allowed_tools == list(spec.default_tools)
        assert plan.tasks[0].expected_output_kind == spec.default_output_kind


def test_mock_agent_registration_is_visible_to_planner_without_scheduler_change() -> None:
    graph = object()
    registry = build_default_agent_registry()
    mock = replace(
        registry.get("document"),
        agent_id="mock_data",
        display_name="Mock Data Agent",
        capabilities=frozenset({"structured_data"}),
        allowed_tools=frozenset({"read_mock_data"}),
        default_tools=("read_mock_data",),
        output_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
        graph_factory=lambda: graph,
    )
    registry.register(mock)
    planner = ValidatedSupervisorPlanner(agent_registry=registry)

    assert planner.resolve_agent("mock_data") is mock
    assert mock.graph_factory is not None and mock.graph_factory() is graph
    assert "mock_data" in {item.agent_id for item in planner.available_agents()}
    with pytest.raises(ValueError, match="not allowed"):
        registry.require_tools("mock_data", ["save_knowledge_card"])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(mock)


def test_registry_rejects_default_tool_outside_allowlist() -> None:
    source = build_default_agent_registry().get("document")
    with pytest.raises(ValueError, match="default_tools"):
        replace(source, allowed_tools=frozenset())


def test_spec_freezes_collection_inputs() -> None:
    source = build_default_agent_registry().get("document")
    tools = set(source.allowed_tools)
    copy = replace(source, allowed_tools=tools)
    tools.clear()
    assert copy.allowed_tools == source.allowed_tools


def test_empty_registry_does_not_implicitly_register_specialists() -> None:
    with pytest.raises(KeyError, match="Unknown Agent"):
        AgentRegistry().get("document")
