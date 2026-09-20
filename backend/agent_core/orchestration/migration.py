from __future__ import annotations

import os
from typing import Literal

from backend.models.agent_orchestration import OrchestrationLane
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService

MultiAgentEngine = Literal["typed", "legacy", "off"]
MultiAgentRollout = Literal["simple", "single", "workflow"]
_ENGINE_ENV_NAME = "AITRANS_MULTI_AGENT_ENGINE"
_ROLLOUT_ENV_NAME = "AITRANS_MULTI_AGENT_ROLLOUT"


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
    "MultiAgentEngine",
    "MultiAgentRollout",
    "build_migration_bridge",
    "resolve_multi_agent_engine",
    "resolve_multi_agent_rollout",
]
