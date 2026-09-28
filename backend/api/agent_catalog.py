from __future__ import annotations

from fastapi import APIRouter

from backend.agent_core.orchestration.agent_registry import build_default_agent_registry
from backend.models.agent_runtime_debug import AgentCatalogEntry, AgentCatalogResponse

router = APIRouter(prefix="/api/agent", tags=["agent-catalog"])

_AGENT_ICONS = {
    "document": "file-text",
    "research": "microscope",
    "writer": "pen-line",
    "curator": "network",
}


@router.get("/catalog", response_model=AgentCatalogResponse)
def get_agent_catalog() -> AgentCatalogResponse:
    """Return public identity metadata only; implementation and tool details stay private."""

    registry = build_default_agent_registry()
    return AgentCatalogResponse(
        agents=[
            AgentCatalogEntry(
                agent_id=spec.agent_id,
                name=spec.display_name,
                description=spec.description,
                capabilities=sorted(spec.capabilities),
                version=spec.version,
                icon=_AGENT_ICONS.get(spec.agent_id, "bot"),
            )
            for spec in registry.list_agents()
        ]
    )


__all__ = ["get_agent_catalog", "router"]
