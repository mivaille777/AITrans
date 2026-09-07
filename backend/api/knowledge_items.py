from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.knowledge_dependencies import get_knowledge_library_service
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.knowledge.domain import KnowledgeItem, KnowledgeItemType
from backend.models.knowledge_workspace_api import (
    KnowledgeItemCreateRequest,
    KnowledgeItemDeleteResponse,
    KnowledgeItemListResponse,
    KnowledgeItemUpdateRequest,
)
from backend.services.knowledge_library_service import KnowledgeLibraryService
from backend.knowledge.service import KnowledgeWorkspaceService

router = APIRouter(prefix="/api/knowledge/items", tags=["knowledge"])
WorkspaceDependency = Annotated[
    KnowledgeWorkspaceService,
    Depends(get_knowledge_workspace_service),
]
LibraryDependency = Annotated[
    KnowledgeLibraryService,
    Depends(get_knowledge_library_service),
]


def _source_type(source_uri: str) -> str:
    return Path(urlparse(source_uri).path).suffix.lower().lstrip(".") or "unknown"


def _sync_document_resources(
    workspace: KnowledgeWorkspaceService,
    library: KnowledgeLibraryService,
) -> None:
    for record in library.list_documents():
        source_type = _source_type(record.source_uri)
        workspace.ensure_document_resource(
            document_id=record.document_id,
            title=record.title,
            source_uri=record.source_uri,
            source_type=source_type,
            item_type=(
                KnowledgeItemType.PAPER
                if source_type == "pdf"
                else KnowledgeItemType.DOCUMENT
            ),
        )


def _item_or_404(item_id: str, workspace: KnowledgeWorkspaceService) -> KnowledgeItem:
    item = workspace.get_item(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge item not found.",
        )
    return item


@router.get("", response_model=KnowledgeItemListResponse)
def list_knowledge_items(
    workspace: WorkspaceDependency,
    library: LibraryDependency,
    item_type: KnowledgeItemType | None = None,
) -> KnowledgeItemListResponse:
    _sync_document_resources(workspace, library)
    items = workspace.list_items(item_type=item_type)
    return KnowledgeItemListResponse(total=len(items), items=items)


@router.get("/{item_id}", response_model=KnowledgeItem)
def get_knowledge_item(
    item_id: str,
    workspace: WorkspaceDependency,
) -> KnowledgeItem:
    return _item_or_404(item_id, workspace)


@router.post("", response_model=KnowledgeItem, status_code=status.HTTP_201_CREATED)
def create_knowledge_item(
    payload: KnowledgeItemCreateRequest,
    workspace: WorkspaceDependency,
) -> KnowledgeItem:
    if payload.item_type in {KnowledgeItemType.DOCUMENT, KnowledgeItemType.WEB}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Document and web cards must be created from a source resource.",
        )
    try:
        return workspace.create_item(
            item_type=payload.item_type,
            title=payload.title,
            summary=payload.summary,
            source_uri=payload.source_uri,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.patch("/{item_id}", response_model=KnowledgeItem)
def update_knowledge_item(
    item_id: str,
    payload: KnowledgeItemUpdateRequest,
    workspace: WorkspaceDependency,
) -> KnowledgeItem:
    existing = _item_or_404(item_id, workspace)
    if (
        payload.item_type in {KnowledgeItemType.DOCUMENT, KnowledgeItemType.WEB}
        and existing.resource_document_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Document and web cards must remain attached to a source resource.",
        )
    try:
        updated = workspace.update_item(
            item_id,
            item_type=payload.item_type,
            title=payload.title,
            summary=payload.summary,
            source_uri=payload.source_uri,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge item not found.",
        )
    return updated


@router.delete("/{item_id}", response_model=KnowledgeItemDeleteResponse)
def delete_knowledge_item(
    item_id: str,
    workspace: WorkspaceDependency,
) -> KnowledgeItemDeleteResponse:
    _item_or_404(item_id, workspace)
    return KnowledgeItemDeleteResponse(
        item_id=item_id,
        deleted=workspace.delete_item(item_id),
    )


__all__ = ["router"]
