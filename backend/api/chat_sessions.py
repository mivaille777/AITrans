from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import get_filesystem_workspace_service
from backend.services.chat_session_service import (
    ChatSessionConfiguration,
    ChatSessionService,
)

router = APIRouter(prefix="/api/companion/sessions", tags=["chat-sessions"])


@lru_cache(maxsize=1)
def get_chat_session_service() -> ChatSessionService:
    return ChatSessionService(get_filesystem_workspace_service())


Service = Annotated[ChatSessionService, Depends(get_chat_session_service)]


@lru_cache(maxsize=1)
def get_workspace_file_service():
    from backend.services.workspace_file_service import WorkspaceFileService
    return WorkspaceFileService(get_filesystem_workspace_service())


def _workspace(session_id, service, *, write=False):
    config = service.get(session_id)
    if not config.filesystem_workspace_id:
        raise HTTPException(409, "请先选择工作区。")
    if write and (config.filesystem_access == "read_only" or config.pending_run_id):
        raise HTTPException(409, "当前为只读或存在待确认计划，不能修改文件。")
    return config


def _file_error(exc):
    return HTTPException(409, {"code": getattr(exc, "code", "file_operation_failed"), "message": str(exc)})


@router.get("/{session_id}/workspace")
def browse_workspace(session_id: str, service: Service, directory: str = "", offset: int = 0):
    if offset < 0 or offset > 100000 or len(directory) > 1024:
        raise HTTPException(400, "文件列表参数无效。")
    config = _workspace(session_id, service)
    try:
        files = get_workspace_file_service()
        root = files.workspaces.active_root_path(config.filesystem_workspace_id)
        return {**files.list(config.filesystem_workspace_id, directory, offset=offset),
                "display_path": str(root), "filesystem_access": config.filesystem_access}
    except (ValueError, OSError) as exc:
        raise _file_error(exc) from exc


@router.get("/{session_id}/workspace/text")
def preview_workspace_text(session_id: str, relative_path: str, service: Service, start_line: int = 1):
    if start_line < 1:
        raise HTTPException(400, "起始行无效。")
    config = _workspace(session_id, service)
    try:
        return get_workspace_file_service().read(config.filesystem_workspace_id, relative_path, start_line)
    except (ValueError, OSError) as exc:
        raise _file_error(exc) from exc


@router.get("/{session_id}/workspace/changes")
def workspace_changes(session_id: str, service: Service):
    config = _workspace(session_id, service)
    return get_workspace_file_service().changes(config.filesystem_workspace_id, session_id)


@router.get("/{session_id}/workspace/location")
def workspace_location(session_id: str, relative_path: str, service: Service):
    config = _workspace(session_id, service)
    try:
        target = get_workspace_file_service().path(config.filesystem_workspace_id, relative_path)
        if not target.exists():
            raise ValueError("目标已不存在。")
        return {"resource_url": target.as_uri(), "kind": "directory" if target.is_dir() else "file"}
    except (ValueError, OSError) as exc:
        raise _file_error(exc) from exc


class UndoPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class UndoApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_token: str = Field(pattern=r"^[a-f0-9]{32}$")


@router.post("/{session_id}/workspace/undo/preview")
def preview_undo(session_id: str, payload: UndoPreviewRequest, service: Service):
    config = _workspace(session_id, service, write=True)
    try:
        return get_workspace_file_service().undo_preview(config.filesystem_workspace_id, session_id, payload.change_id)
    except (ValueError, OSError) as exc:
        raise _file_error(exc) from exc


@router.post("/{session_id}/workspace/undo/apply")
def apply_undo(session_id: str, payload: UndoApplyRequest, service: Service):
    config = _workspace(session_id, service, write=True)
    try:
        return get_workspace_file_service().undo_confirmed(config.filesystem_workspace_id, session_id, payload.approval_token)
    except (ValueError, OSError) as exc:
        raise _file_error(exc) from exc


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filesystem_workspace_id: str | None = Field(default=None, max_length=128)
    execution_mode: Literal["react", "plan_execute"] | None = None
    filesystem_access: Literal["read_only", "read_write"] | None = None


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@router.get("/{session_id}", response_model=ChatSessionConfiguration)
def get_configuration(session_id: str, service: Service):
    return service.get(session_id)


@router.patch("/{session_id}", response_model=ChatSessionConfiguration)
def update_configuration(
    session_id: str, payload: ConfigurationUpdate, service: Service
):
    try:
        return service.update(session_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{session_id}/files", response_model=ChatSessionConfiguration)
def import_file(session_id: str, payload: ImportRequest, service: Service):
    try:
        return service.import_file(session_id, payload.path)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete(
    "/{session_id}/files/{attachment_id}", response_model=ChatSessionConfiguration
)
def detach_file(session_id: str, attachment_id: str, service: Service):
    try:
        return service.detach(session_id, attachment_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
