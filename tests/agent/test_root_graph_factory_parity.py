from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from backend.agent_core.orchestration.specialist_adapter import specialist_node_name
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_graph import studio
from backend.agent_graph.root_agent_graph import RootAgentGraph


def _signature(graph):
    view = graph.get_graph()
    return (
        frozenset(view.nodes),
        frozenset(
            (edge.source, edge.target, edge.conditional, edge.data)
            for edge in view.edges
        ),
    )


class _NoCallService:
    def __getattr__(self, name):
        raise AssertionError(f"graph construction called service method {name}")


def test_studio_and_production_root_graphs_have_the_same_topology(monkeypatch):
    def unexpected_dependency():
        raise AssertionError("Studio graph construction resolved a runtime dependency")

    monkeypatch.setattr(studio, "get_product_agent_service", unexpected_dependency)
    monkeypatch.setattr(studio, "get_conversation_store_service", unexpected_dependency)
    monkeypatch.setattr(studio, "get_companion_ownership_service", unexpected_dependency)

    production = RootAgentGraph(ProductAgentRuntimeAdapter(_NoCallService()))
    studio_graph = studio.make_root_graph()

    assert _signature(studio_graph) == _signature(production.compiled_graph)
    assert set(RootAgentGraph.node_names) <= set(production.compiled_graph.get_graph().nodes)


def test_native_studio_graph_exposes_the_four_registered_compiled_specialists(monkeypatch):
    monkeypatch.setenv("AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT", "true")
    graph = studio.make_root_graph()
    nodes = set(graph.get_graph().nodes)

    assert {
        specialist_node_name(agent_id)
        for agent_id in ("document", "research", "writer", "curator")
    } <= nodes


def test_explicit_native_studio_entry_preserves_compat_default(monkeypatch):
    monkeypatch.setenv("AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT", "false")

    def unexpected_dependency():
        raise AssertionError("Studio graph construction resolved a runtime dependency")

    monkeypatch.setattr(studio, "get_product_agent_service", unexpected_dependency)
    monkeypatch.setattr(studio, "get_knowledge_workspace_service", unexpected_dependency)
    native = studio.make_native_root_graph()
    nodes = set(native.get_graph().nodes)

    assert {
        "route_orchestration", "resolve_scope", "load_memory_snapshot",
        "plan_tasks", "validate_plan", "dispatch_frontier",
        "advance_frontier", "finalize_task_graph",
        *(specialist_node_name(agent_id)
          for agent_id in ("document", "research", "writer", "curator")),
    } <= nodes
    assert "plan_tasks" not in studio.make_root_graph().get_graph().nodes
    assert len(list(native.get_subgraphs())) == 4
    assert {
        specialist_node_name(agent_id)
        for agent_id in ("document", "research", "writer", "curator")
    } <= {
        edge.target for edge in native.get_graph().edges
        if edge.source == "dispatch_frontier"
    }


def test_studio_graph_schemas_support_python_311_runtime_context(monkeypatch):
    monkeypatch.setenv("AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT", "false")
    for graph in (studio.make_root_graph(), studio.make_native_root_graph()):
        assert graph.get_input_jsonschema()["type"] == "object"
        assert graph.get_output_jsonschema()["type"] == "object"
        context = graph.get_context_jsonschema()
        assert not {"event_sink", "control", "resource_manager"} & set(
            context["properties"]
        )
        for _, specialist in graph.get_subgraphs():
            assert specialist.get_input_jsonschema()["type"] == "object"
            assert specialist.get_output_jsonschema()["type"] == "object"


def test_root_graph_factory_keeps_persistent_and_temporary_checkpoint_rules():
    checkpointer = InMemorySaver()
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(_NoCallService()),
        checkpointer=checkpointer,
    )

    assert graph.compiled_graph.checkpointer is checkpointer
    assert graph._temporary_compiled.checkpointer is None


def test_root_graph_construction_does_not_call_service_adapter():
    graph = RootAgentGraph(ProductAgentRuntimeAdapter(_NoCallService()))

    assert graph.compiled_graph is not None
    assert graph._temporary_compiled is not None
