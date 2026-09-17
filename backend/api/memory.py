from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.memory_dependencies import get_memory_coordinator
from backend.memory.repository import MemoryConflictError
from backend.models.memory import (
    MemoryCreateRequest,
    MemoryForgetRequest,
    MemoryItem,
    MemoryListResponse,
    MemoryStatus,
    MemoryUpdateRequest,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])
MemoryCoordinatorDependency = Annotated[object, Depends(get_memory_coordinator)]
LOCAL_PROFILE_ID = "local-default"


def _raise_memory_error(exc: Exception) -> None:
    if isinstance(exc, MemoryConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
    ) from exc


@router.get("/items", response_model=MemoryListResponse)
def list_memory_items(
    service: MemoryCoordinatorDependency,
    workspace_id: Annotated[str | None, Query(max_length=128)] = None,
    item_status: Annotated[MemoryStatus | None, Query(alias="status")] = None,
) -> MemoryListResponse:
    return MemoryListResponse(
        items=list(
            service.list_items(
                profile_id=LOCAL_PROFILE_ID,
                workspace_id=workspace_id,
                status=item_status,
            )
        )
    )


@router.post("/items", response_model=MemoryItem, status_code=status.HTTP_201_CREATED)
def create_memory_item(
    payload: MemoryCreateRequest,
    service: MemoryCoordinatorDependency,
) -> MemoryItem:
    try:
        return service.remember(
            operation_id=payload.operation_id,
            profile_id=LOCAL_PROFILE_ID,
            workspace_id=payload.workspace_id,
            kind=payload.kind,
            content=payload.content,
            source_ref=f"explicit-api:{payload.operation_id}",
            metadata=payload.metadata,
        )
    except (MemoryConflictError, ValueError) as exc:
        _raise_memory_error(exc)
        raise AssertionError("unreachable")


@router.patch("/items/{item_id}", response_model=MemoryItem)
def update_memory_item(
    item_id: str,
    payload: MemoryUpdateRequest,
    service: MemoryCoordinatorDependency,
) -> MemoryItem:
    try:
        return service.update(
            operation_id=payload.operation_id,
            profile_id=LOCAL_PROFILE_ID,
            item_id=item_id,
            expected_version=payload.expected_version,
            content=payload.content,
            metadata=payload.metadata,
            activate=payload.activate,
        )
    except (MemoryConflictError, ValueError) as exc:
        _raise_memory_error(exc)
        raise AssertionError("unreachable")


@router.delete("/items/{item_id}", response_model=MemoryItem)
def forget_memory_item(
    item_id: str,
    payload: MemoryForgetRequest,
    service: MemoryCoordinatorDependency,
) -> MemoryItem:
    try:
        return service.forget(
            profile_id=LOCAL_PROFILE_ID,
            item_id=item_id,
            expected_version=payload.expected_version,
        )
    except (MemoryConflictError, ValueError) as exc:
        _raise_memory_error(exc)
        raise AssertionError("unreachable")


__all__ = ["LOCAL_PROFILE_ID", "router"]
