"""User approval endpoints for sandbox permission requests."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_sandbox_approval_service
from backend.models.sandbox_approval import SandboxApprovalRequest
from backend.services.sandbox_approval_service import (
    SandboxApprovalError,
    SandboxApprovalService,
)

router = APIRouter(prefix="/api/sandbox/approvals", tags=["sandbox-approvals"])
ApprovalServiceDependency = Annotated[
    SandboxApprovalService,
    Depends(get_sandbox_approval_service),
]


def _raise_http_error(error: SandboxApprovalError) -> NoReturn:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from error


@router.get("/pending", response_model=list[SandboxApprovalRequest])
def list_pending_sandbox_approvals(
    service: ApprovalServiceDependency,
) -> list[SandboxApprovalRequest]:
    return service.list_pending()


@router.post("/{approval_id}/approve", response_model=SandboxApprovalRequest)
def approve_sandbox_approval(
    approval_id: str,
    service: ApprovalServiceDependency,
) -> SandboxApprovalRequest:
    try:
        return service.approve(approval_id)
    except SandboxApprovalError as exc:
        _raise_http_error(exc)


@router.post("/{approval_id}/deny", response_model=SandboxApprovalRequest)
def deny_sandbox_approval(
    approval_id: str,
    service: ApprovalServiceDependency,
) -> SandboxApprovalRequest:
    try:
        return service.deny(approval_id)
    except SandboxApprovalError as exc:
        _raise_http_error(exc)


__all__ = ["router"]
