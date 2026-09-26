"""Approval creation and apply endpoints for sandbox workspace changesets."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import get_workspace_apply_service
from backend.models.sandbox_approval import SandboxApprovalRequest
from backend.sandbox.workspace_snapshot import WorkspaceChangeSet
from backend.services.workspace_apply_service import (
    WorkspaceApplyAuditRecord,
    WorkspaceApplyError,
    WorkspaceApplyResult,
    WorkspaceApplyService,
)

router = APIRouter(prefix="/api/sandbox/workspaces", tags=["sandbox-workspaces"])


class WorkspaceChangesetApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changeset: WorkspaceChangeSet


class WorkspaceChangesetApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changeset: WorkspaceChangeSet
    approval_id: str = Field(min_length=1, max_length=128)


WorkspaceApplyServiceDependency = Annotated[
    WorkspaceApplyService,
    Depends(get_workspace_apply_service),
]


def _raise_http_error(error: WorkspaceApplyError) -> NoReturn:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from error


@router.post("/changesets/approval", response_model=SandboxApprovalRequest)
def request_workspace_changeset_approval(
    payload: WorkspaceChangesetApprovalRequest,
    service: WorkspaceApplyServiceDependency,
) -> SandboxApprovalRequest:
    try:
        return service.request_approval(payload.changeset)
    except WorkspaceApplyError as exc:
        _raise_http_error(exc)


@router.post("/changesets/apply", response_model=WorkspaceApplyResult)
def apply_workspace_changeset(
    payload: WorkspaceChangesetApplyRequest,
    service: WorkspaceApplyServiceDependency,
) -> WorkspaceApplyResult:
    try:
        return service.apply(
            payload.changeset,
            approval_id=payload.approval_id,
        )
    except WorkspaceApplyError as exc:
        _raise_http_error(exc)


@router.get("/apply-audit", response_model=list[WorkspaceApplyAuditRecord])
def list_workspace_apply_audit(
    service: WorkspaceApplyServiceDependency,
    limit: int = 100,
) -> list[WorkspaceApplyAuditRecord]:
    try:
        return service.list_audit(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["router"]
