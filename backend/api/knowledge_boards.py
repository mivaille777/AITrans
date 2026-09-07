from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.knowledge_board_dependencies import get_knowledge_board_service
from backend.knowledge.board_domain import KnowledgeBoard, KnowledgeBoardNode
from backend.knowledge.board_service import KnowledgeBoardService
from backend.models.knowledge_board_api import (
    KnowledgeBoardCreateRequest,
    KnowledgeBoardDeleteResponse,
    KnowledgeBoardListResponse,
    KnowledgeBoardNodeDeleteResponse,
    KnowledgeBoardNodeUpsertRequest,
    KnowledgeBoardSnapshotResponse,
)

router = APIRouter(prefix="/api/knowledge/boards", tags=["knowledge"])
BoardDependency = Annotated[KnowledgeBoardService, Depends(get_knowledge_board_service)]


def _board_or_404(board_id: str, service: KnowledgeBoardService) -> KnowledgeBoard:
    board = service.get_board(board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Knowledge board not found.")
    return board


@router.get("", response_model=KnowledgeBoardListResponse)
def list_knowledge_boards(service: BoardDependency) -> KnowledgeBoardListResponse:
    boards = service.list_boards()
    return KnowledgeBoardListResponse(total=len(boards), boards=boards)


@router.post("", response_model=KnowledgeBoard, status_code=status.HTTP_201_CREATED)
def create_knowledge_board(
    payload: KnowledgeBoardCreateRequest,
    service: BoardDependency,
) -> KnowledgeBoard:
    try:
        return service.create_board(name=payload.name, description=payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{board_id}", response_model=KnowledgeBoardSnapshotResponse)
def get_knowledge_board(
    board_id: str,
    service: BoardDependency,
) -> KnowledgeBoardSnapshotResponse:
    board = _board_or_404(board_id, service)
    return KnowledgeBoardSnapshotResponse(
        board=board,
        nodes=service.list_nodes(board_id),
    )


@router.put("/{board_id}/nodes/{item_id}", response_model=KnowledgeBoardNode)
def upsert_knowledge_board_node(
    board_id: str,
    item_id: str,
    payload: KnowledgeBoardNodeUpsertRequest,
    service: BoardDependency,
) -> KnowledgeBoardNode:
    _board_or_404(board_id, service)
    try:
        return service.upsert_node(
            board_id=board_id,
            item_id=item_id,
            x=payload.x,
            y=payload.y,
            width=payload.width,
            height=payload.height,
            collapsed=payload.collapsed,
            z_index=payload.z_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/{board_id}/nodes/{item_id}",
    response_model=KnowledgeBoardNodeDeleteResponse,
)
def delete_knowledge_board_node(
    board_id: str,
    item_id: str,
    service: BoardDependency,
) -> KnowledgeBoardNodeDeleteResponse:
    _board_or_404(board_id, service)
    return KnowledgeBoardNodeDeleteResponse(
        board_id=board_id,
        item_id=item_id,
        deleted=service.remove_node(board_id=board_id, item_id=item_id),
    )


@router.delete("/{board_id}", response_model=KnowledgeBoardDeleteResponse)
def delete_knowledge_board(
    board_id: str,
    service: BoardDependency,
) -> KnowledgeBoardDeleteResponse:
    _board_or_404(board_id, service)
    try:
        deleted = service.delete_board(board_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeBoardDeleteResponse(board_id=board_id, deleted=deleted)


__all__ = ["router"]
