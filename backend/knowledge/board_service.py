from __future__ import annotations

from uuid import uuid4

from backend.knowledge.board_domain import (
    KnowledgeBoard,
    KnowledgeBoardNode,
    utc_now,
)
from backend.knowledge.board_repository import SqliteKnowledgeBoardRepository
from backend.knowledge.service import KnowledgeWorkspaceService

DEFAULT_BOARD_ID = "kb_default"


class KnowledgeBoardService:
    def __init__(
        self,
        repository: SqliteKnowledgeBoardRepository,
        workspace: KnowledgeWorkspaceService,
    ) -> None:
        self._repository = repository
        self._workspace = workspace

    def ensure_default_board(self) -> KnowledgeBoard:
        existing = self._repository.get_board(DEFAULT_BOARD_ID)
        if existing is not None:
            return existing
        return self._repository.save_board(
            KnowledgeBoard(
                board_id=DEFAULT_BOARD_ID,
                name="Research Board",
                description=(
                    "Visual workspace for papers, notes, concepts, and highlights."
                ),
            )
        )

    def create_board(self, *, name: str, description: str = "") -> KnowledgeBoard:
        normalized = name.strip()
        if not normalized:
            raise ValueError("board name must not be empty")
        return self._repository.save_board(
            KnowledgeBoard(
                board_id=f"kb_{uuid4().hex}",
                name=normalized,
                description=description.strip(),
            )
        )

    def get_board(self, board_id: str) -> KnowledgeBoard | None:
        return self._repository.get_board(board_id)

    def list_boards(self) -> list[KnowledgeBoard]:
        self.ensure_default_board()
        return self._repository.list_boards()

    def delete_board(self, board_id: str) -> bool:
        if board_id == DEFAULT_BOARD_ID:
            raise ValueError("default board cannot be deleted")
        return self._repository.delete_board(board_id)

    def list_nodes(self, board_id: str) -> list[KnowledgeBoardNode]:
        if self.get_board(board_id) is None:
            raise ValueError("knowledge board does not exist")
        return self._repository.list_nodes(board_id)

    def upsert_node(
        self,
        *,
        board_id: str,
        item_id: str,
        x: float,
        y: float,
        width: float = 248.0,
        height: float = 156.0,
        collapsed: bool = False,
        z_index: int = 0,
    ) -> KnowledgeBoardNode:
        if self.get_board(board_id) is None:
            raise ValueError("knowledge board does not exist")
        if self._workspace.get_item(item_id) is None:
            raise ValueError("knowledge item does not exist")
        existing = self._repository.get_node(board_id, item_id)
        return self._repository.save_node(
            KnowledgeBoardNode(
                board_id=board_id,
                item_id=item_id,
                x=x,
                y=y,
                width=width,
                height=height,
                collapsed=collapsed,
                z_index=z_index,
                created_at=existing.created_at if existing else utc_now(),
                updated_at=utc_now(),
            )
        )

    def remove_node(self, *, board_id: str, item_id: str) -> bool:
        return self._repository.delete_node(board_id, item_id)


__all__ = ["DEFAULT_BOARD_ID", "KnowledgeBoardService"]
