"""Tools management API, independent of legacy catalog DTOs."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_agent_tool_registry
from backend.models.tool_management import ToolCatalog, ToolDetail, ToolUpdate
from backend.models.tool_test import ToolTestApproval, ToolTestRequest, ToolTestRun
from backend.services.tool_management_service import (
    ToolManagementError,
    ToolManagementService,
)
from backend.services.tool_test_service import ToolTestService

router = APIRouter(prefix="/api/tools", tags=["tools"])


def get_tool_management_service() -> ToolManagementService:
    return ToolManagementService(get_agent_tool_registry())


Service = Annotated[ToolManagementService, Depends(get_tool_management_service)]


@lru_cache(maxsize=1)
def get_tool_test_service():
    from backend.api.dependencies import (
        get_filesystem_workspace_service,
        get_research_workspace_service,
        get_sandbox_approval_service,
    )
    from backend.api.knowledge_dependencies import get_knowledge_library_service

    return ToolTestService(
        get_tool_management_service(),
        approvals=get_sandbox_approval_service(),
        library=get_knowledge_library_service(),
        research=get_research_workspace_service(),
        filesystem=get_filesystem_workspace_service(),
    )


TestService = Annotated[ToolTestService, Depends(get_tool_test_service)]


def close_tool_test_service():
    if get_tool_test_service.cache_info().currsize:
        get_tool_test_service().close()
        get_tool_test_service.cache_clear()


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


@router.post("/{tool_id}/validate")
def validate_test(tool_id: str, payload: ToolTestRequest, service: TestService):
    detail, args, _ = call(lambda: service.validate(tool_id, payload))
    return {"valid": True, "arguments": args, "revision": detail.revision}


@router.post("/{tool_id}/test-runs", response_model=ToolTestRun, status_code=202)
def create_test(tool_id: str, payload: ToolTestRequest, service: TestService):
    return call(lambda: service.create(tool_id, payload))


@router.get("/{tool_id}/test-runs/{run_id}", response_model=ToolTestRun)
def get_test(tool_id: str, run_id: str, service: TestService):
    return call(lambda: service.get(tool_id, run_id))


@router.post("/{tool_id}/test-runs/{run_id}/cancel", response_model=ToolTestRun)
def cancel_test(tool_id: str, run_id: str, service: TestService):
    return call(lambda: service.cancel(tool_id, run_id))


@router.post("/{tool_id}/test-runs/{run_id}/approve", response_model=ToolTestRun)
def approve_test(
    tool_id: str, run_id: str, payload: ToolTestApproval, service: TestService
):
    return call(lambda: service.approve(tool_id, run_id, payload.approval_id))
