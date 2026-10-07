"""Tools management API, independent of legacy catalog DTOs."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_agent_tool_registry
from backend.models.tool_management import ToolCatalog, ToolDetail, ToolUpdate
from backend.services.tool_management_service import (
    ToolManagementError,
    ToolManagementService,
)

router = APIRouter(prefix="/api/tools", tags=["tools"])


def get_tool_management_service() -> ToolManagementService:
    return ToolManagementService(get_agent_tool_registry())


Service = Annotated[ToolManagementService, Depends(get_tool_management_service)]


def call(operation):
    try:
        return operation()
    except ToolManagementError as exc:
        raise HTTPException(exc.status, detail=exc.detail()) from exc


@router.get("", response_model=ToolCatalog)
def list_tools(
    service: Service,
    q: str = Query("", max_length=256),
    category: str = Query("", max_length=128),
    status: str = Query("all", pattern="^(all|enabled|disabled)$"),
    limit: int = Query(100, ge=1, le=200),
    cursor: str | None = Query(None, max_length=2048),
):
    return call(lambda: service.list(q, category, status, limit, cursor))


@router.get("/{tool_id}", response_model=ToolDetail)
def tool_detail(tool_id: str, service: Service):
    return call(lambda: service.detail(tool_id))


@router.patch("/{tool_id}", response_model=ToolDetail)
def update_tool(tool_id: str, payload: ToolUpdate, service: Service):
    return call(lambda: service.update(tool_id, payload))
