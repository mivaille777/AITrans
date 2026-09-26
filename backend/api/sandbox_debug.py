from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from backend.api.dependencies import (
    get_filesystem_workspace_service,
    get_sandbox_debug_service,
    get_sandbox_manager,
    get_sandbox_runtime_health,
)
from backend.models.sandbox_debug import (
    SandboxDebugRunAccepted,
    SandboxDebugRunRequest,
    SandboxDebugTrace,
    SandboxRunSummary,
    SandboxRuntimeHealthResponse,
)
from backend.sandbox.manager import SandboxManager
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.sandbox_debug_service import (
    SandboxDebugError,
    SandboxDebugService,
)

router = APIRouter(prefix="/api/sandbox/debug", tags=["sandbox-debug"])

DebugServiceDependency = Annotated[SandboxDebugService, Depends(get_sandbox_debug_service)]
WorkspaceServiceDependency = Annotated[
    FilesystemWorkspaceService, Depends(get_filesystem_workspace_service)
]


def _require_manager() -> SandboxManager:
    manager = get_sandbox_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="Sandbox runtime is unavailable.")
    return manager


@router.get("/health", response_model=SandboxRuntimeHealthResponse)
def sandbox_debug_health() -> SandboxRuntimeHealthResponse:
    health = get_sandbox_runtime_health()
    return SandboxRuntimeHealthResponse(
        available=health.available,
        runtime=health.runtime,
        image=health.image,
        daemon_ready=health.error_code
        not in {"docker_unavailable", "sandbox_disabled", "invalid_sandbox_image"},
        os_type=health.server_os,
        server_os=health.server_os,
        detail=health.message,
        message=health.message,
        error_code=health.error_code,
    )


@router.get("/runs", response_model=list[SandboxRunSummary])
def list_sandbox_debug_runs(service: DebugServiceDependency) -> list[SandboxRunSummary]:
    return service.list_runs()


@router.post("/runs", response_model=SandboxDebugRunAccepted, status_code=202)
def start_sandbox_debug_run(
    payload: SandboxDebugRunRequest,
    service: DebugServiceDependency,
    workspaces: WorkspaceServiceDependency,
) -> SandboxDebugRunAccepted:
    manager = _require_manager()
    health = manager.health()
    if not health.available:
        raise HTTPException(status_code=503, detail=health.message or "Sandbox runtime is unavailable.")
    try:
        summary = service.start_manual_run(
            code=payload.code,
            filesystem_workspace_id=payload.filesystem_workspace_id.strip(),
            manager=manager,
            workspace_service=workspaces,
        )
    except SandboxDebugError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return SandboxDebugRunAccepted(
        sandbox_id=summary.sandbox_id,
        run_id=summary.run_id,
        status=summary.status,
    )


@router.post("/runs/{sandbox_id}/cancel", response_model=SandboxRunSummary)
def cancel_sandbox_debug_run(
    sandbox_id: str,
    service: DebugServiceDependency,
) -> SandboxRunSummary:
    try:
        return service.cancel(sandbox_id, _require_manager())
    except SandboxDebugError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/runs/{sandbox_id}", response_model=SandboxDebugTrace)
def get_sandbox_debug_run(
    sandbox_id: str,
    service: DebugServiceDependency,
) -> SandboxDebugTrace:
    try:
        return service.get_run(sandbox_id)
    except SandboxDebugError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.websocket("/runs/{sandbox_id}/stream")
async def stream_sandbox_debug_run(websocket: WebSocket, sandbox_id: str) -> None:
    service = get_sandbox_debug_service()
    try:
        service.get_run(sandbox_id)
    except SandboxDebugError as exc:
        await websocket.accept()
        await websocket.send_json({"type": "error", "code": exc.code, "message": str(exc)})
        await websocket.close(code=4404)
        return
    try:
        await service.stream(websocket, sandbox_id)
    except WebSocketDisconnect:
        return


__all__ = ["router"]
