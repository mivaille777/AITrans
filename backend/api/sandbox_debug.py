from __future__ import annotations

from typing import Annotated
from typing import Literal
from urllib.parse import quote
import json
import codecs

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import ValidationError
from backend.services.sandbox_debug_artifacts import read_artifact, export_report

from backend.api.dependencies import (
    get_filesystem_workspace_service,
    get_sandbox_debug_manager,
    get_sandbox_debug_runtime_start_status,
    get_sandbox_debug_service,
    get_sandbox_runtime_health,
    start_sandbox_debug_runtime,
)
from backend.models.sandbox_debug import (
    SandboxDebugRunAccepted,
    SandboxDebugRunRequest,
    SandboxDebugTrace,
    SandboxRunSummary,
    SandboxRuntimeHealthResponse,
    SandboxRuntimeStartStatusResponse,
)
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxRuntimeHealth
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
    manager = get_sandbox_debug_manager()
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Start the Sandbox runtime before running code.",
        )
    return manager


def _health_response(
    health: SandboxRuntimeHealth | None = None,
) -> SandboxRuntimeHealthResponse:
    if health is None:
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


@router.get("/health", response_model=SandboxRuntimeHealthResponse)
def sandbox_debug_health() -> SandboxRuntimeHealthResponse:
    return _health_response()


@router.post("/runtime/start", response_model=SandboxRuntimeStartStatusResponse)
def start_sandbox_debug_runtime_route() -> SandboxRuntimeStartStatusResponse:
    return start_sandbox_debug_runtime()


@router.get("/runtime/start", response_model=SandboxRuntimeStartStatusResponse)
def sandbox_debug_runtime_start_status() -> SandboxRuntimeStartStatusResponse:
    return get_sandbox_debug_runtime_start_status()


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
            retain_content=payload.retain_content,
            execution_kind=payload.execution_kind,
            argv=payload.argv,
            cwd=payload.cwd,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid command arguments or working directory.") from exc
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


@router.get("/runs/{sandbox_id}/report")
def sandbox_debug_report(sandbox_id: str, service: DebugServiceDependency, format: Literal["markdown", "json"] = "markdown") -> dict:
    try:
        return export_report(service.get_run(sandbox_id), format)
    except SandboxDebugError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/runs/{sandbox_id}/files/{file_id}")
def sandbox_debug_artifact(sandbox_id: str, file_id: str, service: DebugServiceDependency, preview: bool = False, inline: bool = False):
    try:
        filename, data = read_artifact(service.get_run(sandbox_id), file_id, _require_manager().artifact_root)
        if inline:
            from backend.services.execution_image_service import image_response
            return image_response(filename, data)
        if preview:
            try:
                text = codecs.getincrementaldecoder("utf-8")().decode(data[:65536], final=len(data) <= 65536)
            except UnicodeDecodeError:
                return {"text": "Binary artifact; use Download to save it.", "truncated": False}
            if "\x00" in text:
                text = "Binary artifact; use Download to save it."
            return {"text": text, "truncated": len(data) > 65536}
        return Response(content=data, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "X-Content-Type-Options": "nosniff"})
    except SandboxDebugError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/runtime/recover")
def recover_sandbox_debug(service: DebugServiceDependency) -> dict:
    return service.recover(_require_manager())


@router.post("/runtime/diagnostics")
def diagnose_sandbox_debug() -> dict:
    manager = _require_manager()
    health = manager.health()
    if not health.available:
        raise HTTPException(status_code=503, detail=health.message)
    # A fixed probe executes under the same immutable sandbox policy.
    result = manager.execute_python("import sys,json,platform,importlib.metadata as m; print(json.dumps({'python':sys.version.split()[0], 'platform':platform.platform(), 'dependencies':{d.metadata['Name']:d.version for d in m.distributions()}}))")
    if result.status != "succeeded":
        raise HTTPException(status_code=503, detail="Runtime environment probe failed.")
    return {"health": _health_response(health).model_dump(), "runtime_info": result.runtime_info, "environment": json.loads(result.stdout)}


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
