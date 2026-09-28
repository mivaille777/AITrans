from __future__ import annotations

import os
from typing import Literal

from backend.models.agent_orchestration import OrchestrationLane
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService

MultiAgentEngine = Literal["typed", "legacy", "off"]
MultiAgentRollout = Literal["simple", "single", "workflow"]
AgentGraphEngine = Literal["compat", "native"]
_ENGINE_ENV_NAME = "AITRANS_MULTI_AGENT_ENGINE"
_ROLLOUT_ENV_NAME = "AITRANS_MULTI_AGENT_ROLLOUT"
_NATIVE_ENV_NAME = "AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT"


def resolve_langgraph_native_multi_agent(value: str | None = None) -> bool:
    """Read the opt-in switch that pins native Root execution for new runs.

    Existing runs keep the engine and graph version recorded when they were
    created; the environment switch never changes an in-progress or resumed run.
    """

    raw = value if value is not None else os.getenv(_NATIVE_ENV_NAME, "false")
    normalized = str(raw or "false").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{_NATIVE_ENV_NAME} must be a boolean; got {normalized!r}")


def resolve_agent_graph_engine(value: str | None = None) -> AgentGraphEngine:
    """Pin the Root topology selected for a newly created Agent run."""

    return "native" if resolve_langgraph_native_multi_agent(value) else "compat"


def resolve_multi_agent_engine(value: str | None = None) -> MultiAgentEngine:
    raw = value if value is not None else os.getenv(_ENGINE_ENV_NAME, "typed")
    normalized = str(raw or "typed").strip().lower()
    if normalized not in {"typed", "legacy", "off"}:
        raise ValueError(
            f"{_ENGINE_ENV_NAME} must be one of typed, legacy, off; got {normalized!r}"
        )
    return normalized  # type: ignore[return-value]


def resolve_multi_agent_rollout(value: str | None = None) -> MultiAgentRollout:
    raw = value if value is not None else os.getenv(_ROLLOUT_ENV_NAME, "single")
    normalized = str(raw or "single").strip().lower()
    if normalized not in {"simple", "single", "workflow"}:
        raise ValueError(
            f"{_ROLLOUT_ENV_NAME} must be one of simple, single, workflow; "
            f"got {normalized!r}"
        )
    return normalized  # type: ignore[return-value]


def build_migration_bridge(
    service: MultiAgentWorkspaceService,
    *,
    orchestrator: object,
    engine: MultiAgentEngine | None = None,
    rollout: MultiAgentRollout | None = None,
) -> MultiAgentRuntimeBridge | None:
    selected = engine or resolve_multi_agent_engine()
    if selected == "off":
        return None
    if selected == "legacy":
        return MultiAgentRuntimeBridge(service)
    selected_rollout = rollout or resolve_multi_agent_rollout()
    if selected_rollout == "simple":
        return None
    return MultiAgentRuntimeBridge(
        service,
        orchestrator=orchestrator,
        maximum_lane=(
            OrchestrationLane.SINGLE
            if selected_rollout == "single"
            else OrchestrationLane.WORKFLOW
        ),
    )


__all__ = [
    "AgentGraphEngine",
    "MultiAgentEngine",
    "MultiAgentRollout",
    "build_migration_bridge",
    "resolve_agent_graph_engine",
    "resolve_langgraph_native_multi_agent",
    "resolve_multi_agent_engine",
    "resolve_multi_agent_rollout",
]
