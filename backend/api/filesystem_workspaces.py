from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import get_filesystem_workspace_service
from backend.services.filesystem_workspace_service import (
    FilesystemWorkspaceError,
    FilesystemWorkspaceLimitError,
    FilesystemWorkspaceRecord,
    FilesystemWorkspaceService,
)

router = APIRouter(prefix="/api/agent/filesystem-workspaces", tags=["filesystem-workspaces"])


class CreateFilesystemWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


class RevokeFilesystemWorkspaceResponse(BaseModel):
    workspace_id: str
    revoked: bool


WorkspaceServiceDependency = Annotated[
    FilesystemWorkspaceService, Depends(get_filesystem_workspace_service)
]


@router.post("", response_model=FilesystemWorkspaceRecord)
def create_filesystem_workspace(
    payload: CreateFilesystemWorkspaceRequest,
    service: WorkspaceServiceDependency,
) -> FilesystemWorkspaceRecord:
    try:
        return service.create(payload.path)
    except FilesystemWorkspaceLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except FilesystemWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[FilesystemWorkspaceRecord])
def list_filesystem_workspaces(
    service: WorkspaceServiceDependency,
) -> list[FilesystemWorkspaceRecord]:
    return service.list()


@router.get("/{workspace_id}", response_model=FilesystemWorkspaceRecord)
def get_filesystem_workspace(
    workspace_id: str,
    service: WorkspaceServiceDependency,
) -> FilesystemWorkspaceRecord:
    try:
        return service.get(workspace_id)
    except FilesystemWorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{workspace_id}", response_model=RevokeFilesystemWorkspaceResponse)
def revoke_filesystem_workspace(
    workspace_id: str,
    service: WorkspaceServiceDependency,
) -> RevokeFilesystemWorkspaceResponse:
    return RevokeFilesystemWorkspaceResponse(
        workspace_id=workspace_id,
        revoked=service.revoke(workspace_id),
    )


__all__ = ["router"]
