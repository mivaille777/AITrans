from __future__ import annotations

import os
from typing import Literal

from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService

MultiAgentEngine = Literal["typed", "legacy", "off"]
_ENV_NAME = "AITRANS_MULTI_AGENT_ENGINE"


def resolve_multi_agent_engine(value: str | None = None) -> MultiAgentEngine:
    raw = value if value is not None else os.getenv(_ENV_NAME, "typed")
    normalized = str(raw or "typed").strip().lower()
    if normalized not in {"typed", "legacy", "off"}:
        raise ValueError(
            f"{_ENV_NAME} must be one of typed, legacy, off; got {normalized!r}"
        )
    return normalized  # type: ignore[return-value]


def build_migration_bridge(
    service: MultiAgentWorkspaceService,
    *,
    orchestrator: object,
    engine: MultiAgentEngine | None = None,
) -> MultiAgentRuntimeBridge | None:
    selected = engine or resolve_multi_agent_engine()
    if selected == "off":
        return None
    if selected == "legacy":
        return MultiAgentRuntimeBridge(service)
    return MultiAgentRuntimeBridge(service, orchestrator=orchestrator)


__all__ = ["MultiAgentEngine", "build_migration_bridge", "resolve_multi_agent_engine"]
