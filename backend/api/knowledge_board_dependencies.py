from __future__ import annotations

from threading import Lock

from app.infrastructure.paths import writable_config_dir
from backend.api.knowledge_workspace_dependencies import (
    DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME,
    get_knowledge_workspace_service,
)
from backend.knowledge.board_repository import SqliteKnowledgeBoardRepository
from backend.knowledge.board_service import KnowledgeBoardService

_service: KnowledgeBoardService | None = None
_lock = Lock()


def get_knowledge_board_service() -> KnowledgeBoardService:
    global _service
    if _service is not None:
        return _service
    with _lock:
        if _service is None:
            workspace = get_knowledge_workspace_service()
            repository = SqliteKnowledgeBoardRepository(
                writable_config_dir() / DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME
            )
            _service = KnowledgeBoardService(repository, workspace)
        return _service


def close_knowledge_board_service() -> None:
    global _service
    with _lock:
        _service = None


__all__ = ["close_knowledge_board_service", "get_knowledge_board_service"]
