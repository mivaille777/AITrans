from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.curator_dependencies import get_curator_commit_service
from backend.models.curator_commit import CuratorCommitReceipt, CuratorCommitRequest
from backend.services.curator_commit_service import (
    CuratorCommitConflictError,
    CuratorCommitError,
    CuratorCommitService,
)

router = APIRouter(prefix="/api/curator", tags=["knowledge-curator"])
CuratorCommitDependency = Annotated[
    CuratorCommitService,
    Depends(get_curator_commit_service),
]


@router.post("/commit", response_model=CuratorCommitReceipt)
def commit_curator_draft(
    payload: CuratorCommitRequest,
    service: CuratorCommitDependency,
) -> CuratorCommitReceipt:
    try:
        return service.apply(**payload.model_dump())
    except CuratorCommitConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except CuratorCommitError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in str(exc).casefold()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/operations/{operation_id}", response_model=CuratorCommitReceipt)
def get_curator_commit_receipt(
    operation_id: str,
    service: CuratorCommitDependency,
) -> CuratorCommitReceipt:
    receipt = service.get_receipt(operation_id)
    if receipt is None:
        raise HTTPException(
            status_code=404, detail="Curator commit operation not found"
        )
    return receipt


__all__ = ["router"]
