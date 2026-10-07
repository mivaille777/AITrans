"""Tools management API, independent of legacy catalog DTOs."""

import asyncio
import json
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_agent_tool_registry
from backend.models.tool_configuration import (
    CustomToolPreset,
    ToolArchiveRequest,
    ToolImportDocument,
    ToolImportRequest,
)
from backend.models.tool_management import ToolCatalog, ToolDetail, ToolUpdate
from backend.models.tool_test import ToolTestApproval, ToolTestRequest, ToolTestRun
from backend.services.sandbox_approval_service import SandboxApprovalError
from backend.services.tool_custom_service import ToolCustomService
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
    from backend.api.agent_runtime_jobs import get_agent_run_store
    from backend.api.dependencies import (
        get_filesystem_workspace_service,
        get_research_workspace_service,
        get_sandbox_approval_service,
    )
    from backend.api.knowledge_dependencies import get_knowledge_library_service
    from backend.services.tool_test_store import ToolTestStore

    return ToolTestService(
        get_tool_management_service(),
        approvals=get_sandbox_approval_service(),
        library=get_knowledge_library_service(),
        research=get_research_workspace_service(),
        filesystem=get_filesystem_workspace_service(),
        store=ToolTestStore(get_agent_run_store().storage_path),
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
    except SandboxApprovalError as exc:
        raise HTTPException(
            exc.status_code,
            detail={"code": exc.code, "message": str(exc), "field_errors": []},
        ) from exc


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


@router.post("/custom", response_model=ToolDetail, status_code=201)
def create_custom_tool(payload: CustomToolPreset, service: Service):
    return call(lambda: ToolCustomService(service).create(payload))


@router.post("/imports/preview")
def preview_import(payload: ToolImportDocument, service: Service):
    return call(lambda: ToolCustomService(service).preview(payload))


@router.post("/imports")
def import_tools(payload: ToolImportRequest, service: Service):
    return call(lambda: ToolCustomService(service).apply(payload))


@router.post("/{tool_id}/archive", response_model=ToolDetail)
def archive_tool(tool_id: str, payload: ToolArchiveRequest, service: Service):
    return call(lambda: ToolCustomService(service).archive(tool_id, payload.revision))


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


@router.get("/{tool_id}/test-runs")
def test_history(
    tool_id: str,
    service: TestService,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, max_length=2048),
):
    call(lambda: service.management.detail(tool_id))
    if not service.store:
        return {"items": [], "next_cursor": None}
    return call(lambda: service.store.history(tool_id, limit=limit, before=cursor))


@router.get("/{tool_id}/test-runs/{run_id}/events")
async def test_events(
    tool_id: str,
    run_id: str,
    request: Request,
    service: TestService,
    after: int = Query(0, ge=0),
):
    call(lambda: service.get(tool_id, run_id))
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
        if cursor < 0:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(422, detail="Invalid event cursor") from exc

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            events = (
                await asyncio.to_thread(service.store.events, run_id, cursor)
                if service.store
                else []
            )
            for event in events:
                cursor = event["seq"]
                yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
            current = await asyncio.to_thread(service.get, tool_id, run_id)
            if current.finished_at and current.execution_state == "stopped":
                # A worker can finish between the first events read and get().
                # Drain the final committed events before closing the stream.
                tail = (
                    await asyncio.to_thread(service.store.events, run_id, cursor)
                    if service.store
                    else []
                )
                for event in tail:
                    cursor = event["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                yield "event: closed\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{tool_id}/test-runs/{run_id}/event-log")
def test_event_log(
    tool_id: str, run_id: str, service: TestService, after: int = Query(0, ge=0)
):
    call(lambda: service.get(tool_id, run_id))
    return {"items": service.store.events(run_id, after) if service.store else []}
