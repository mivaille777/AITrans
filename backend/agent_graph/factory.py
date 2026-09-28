"""Shared topology builder for production and LangSmith Studio Root graphs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from backend.agent_core.reliability import is_transient_provider_error
from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    PREVIOUS_NATIVE_AGENT_GRAPH_VERSION,
    SUPPORTED_AGENT_GRAPH_VERSIONS,
)


def build_root_graph(
    *,
    state_schema: Any,
    context_schema: Any,
    nodes: Mapping[str, Callable[..., Any]],
    route_branch: Callable[..., str],
    orchestration_branch: Callable[..., str],
    decision_branch: Callable[..., str],
    observation_branch: Callable[..., str],
    dispatch_branch: Callable[..., Any] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    graph_version: str = CURRENT_AGENT_GRAPH_VERSION,
    engine: str = "compat",
    native_send_dispatch: bool = False,
) -> tuple[Any, Any]:
    """Compile durable and temporary graphs from the canonical Root topology.

    Handlers and runtime dependencies are supplied by ``ReadingAgentGraph``;
    this function owns only node registration, edges, and compile policy. The
    temporary graph deliberately has no checkpointer.
    """

    selected_version = str(graph_version or "").strip()
    if selected_version not in SUPPORTED_AGENT_GRAPH_VERSIONS:
        raise ValueError(f"unsupported Agent graph_version: {selected_version}")

    selected_engine = str(engine or "compat").strip().lower()
    if selected_engine not in {"compat", "native"}:
        raise ValueError(f"unsupported Agent engine: {selected_engine}")
    native_topology = (
        selected_version
        in {PREVIOUS_NATIVE_AGENT_GRAPH_VERSION, CURRENT_AGENT_GRAPH_VERSION}
        and selected_engine == "native"
    )
    send_topology = (
        native_topology
        and selected_version == CURRENT_AGENT_GRAPH_VERSION
        and native_send_dispatch
    )
    builder = StateGraph(state_schema, context_schema=context_schema)
    active_nodes = dict(nodes)
    if native_topology:
        required = {
            "route_orchestration",
            "resolve_scope",
            "load_memory_snapshot",
            "plan_tasks",
            "validate_plan",
            "block_orchestration",
        }
        missing = sorted(required - set(active_nodes))
        if missing:
            raise ValueError(f"native Root topology lacks nodes: {missing}")
        if send_topology:
            send_required = {
                "dispatch_frontier",
                "advance_frontier",
                "finalize_task_graph",
            }
            missing_send = sorted(send_required - set(active_nodes))
            if missing_send or dispatch_branch is None:
                raise ValueError(
                    "native Send topology lacks nodes or dispatch branch: "
                    f"nodes={missing_send}, branch={dispatch_branch is not None}"
                )
    else:
        active_nodes = {
            name: handler
            for name, handler in active_nodes.items()
            if name
            not in {
                "route_orchestration",
                "resolve_scope",
                "load_memory_snapshot",
                "plan_tasks",
                "validate_plan",
                "block_orchestration",
                "dispatch_frontier",
                "advance_frontier",
                "finalize_task_graph",
            }
        }
    if native_topology and not send_topology:
        active_nodes = {
            name: handler
            for name, handler in active_nodes.items()
            if name not in {"dispatch_frontier", "advance_frontier", "finalize_task_graph"}
            and not name.startswith("specialist_")
        }
    for name, handler in active_nodes.items():
        input_schema = getattr(handler, "input_schema", None)
        retry_policy = None
        # These Root nodes are provider/planning decisions with no business
        # write side effects. Tool nodes are intentionally excluded: their
        # allowlist and effect are enforced at the tool execution boundary.
        if native_topology and name in {
            "route_orchestration",
            "plan_tasks",
            "route_request",
            "decide_react",
        }:
            retry_policy = RetryPolicy(
                initial_interval=0.1,
                backoff_factor=2.0,
                max_interval=0.5,
                max_attempts=3,
                jitter=False,
                retry_on=is_transient_provider_error,
            )
        if input_schema is None:
            builder.add_node(name, handler, retry_policy=retry_policy)
        else:
            builder.add_node(
                name,
                handler,
                input_schema=input_schema,
                retry_policy=retry_policy,
            )

    builder.add_edge(START, "resolve_context")
    # Acquire durable conversation ownership before specialists read scope or
    # memory, so two windows cannot launch competing task graphs.
    builder.add_edge("resolve_context", "prepare_conversation")
    if native_topology:
        builder.add_edge("prepare_conversation", "route_orchestration")
        builder.add_conditional_edges(
            "route_orchestration",
            orchestration_branch,
            {
                "fast": "knowledge_access",
                "blocked": "block_orchestration",
                "plan": "resolve_scope",
            },
        )
        builder.add_edge("block_orchestration", "finalize_conversation")
        builder.add_edge("resolve_scope", "load_memory_snapshot")
        builder.add_edge("load_memory_snapshot", "plan_tasks")
        builder.add_edge("plan_tasks", "validate_plan")
        if send_topology:
            builder.add_edge("validate_plan", "dispatch_frontier")
            builder.add_conditional_edges(
                "dispatch_frontier",
                dispatch_branch,
                {"finalize": "finalize_task_graph"},
            )
            specialist_nodes = sorted(
                name
                for name in active_nodes
                if name.startswith("specialist_")
            )
            if not specialist_nodes:
                raise ValueError("native Send topology has no registered specialist subgraphs")
            for name in specialist_nodes:
                builder.add_edge(name, "advance_frontier")
            builder.add_edge("advance_frontier", "dispatch_frontier")
            builder.add_edge("finalize_task_graph", "run_collaboration")
        else:
            builder.add_edge("validate_plan", "run_collaboration")
    else:
        # MA04 and MA05/compat retain the exact established topology.
        builder.add_edge("prepare_conversation", "run_collaboration")
    builder.add_edge("run_collaboration", "knowledge_access")
    builder.add_edge("knowledge_access", "knowledge_scope")
    builder.add_edge("knowledge_scope", "route_request")
    builder.add_conditional_edges(
        "route_request",
        route_branch,
        {
            "complex": "start_react",
            "direct": "execute_direct",
            "completed": "finalize_conversation",
        },
    )
    builder.add_edge("execute_direct", "finalize_conversation")
    builder.add_edge("start_react", "decide_react")
    builder.add_conditional_edges(
        "decide_react",
        decision_branch,
        {
            "tool": "execute_react_tool",
            "final": "finalize_react",
            "limit": "finalize_react",
        },
    )
    builder.add_conditional_edges(
        "execute_react_tool",
        observation_branch,
        {
            "continue": "decide_react",
            "finalize": "finalize_react",
            "confirmation": "finalize_conversation",
        },
    )
    builder.add_edge("finalize_react", "finalize_conversation")
    builder.add_edge("finalize_conversation", END)

    return builder.compile(checkpointer=checkpointer), builder.compile()


__all__ = ["build_root_graph"]
