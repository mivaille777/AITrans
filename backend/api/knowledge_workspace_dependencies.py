from __future__ import annotations

from threading import Lock

from app.infrastructure.paths import writable_config_dir
from backend.knowledge.repository import SqliteKnowledgeRepository
from backend.knowledge.service import KnowledgeWorkspaceService

DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME = "knowledge_workspace.sqlite3"

_service: KnowledgeWorkspaceService | None = None
_service_lock = Lock()


def get_knowledge_workspace_service() -> KnowledgeWorkspaceService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            repository = SqliteKnowledgeRepository(
                writable_config_dir() / DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME
            )
            _service = KnowledgeWorkspaceService(repository)
        return _service


def close_knowledge_workspace_service() -> None:
    global _service
    with _service_lock:
        _service = None


__all__ = [
    "DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME",
    "close_knowledge_workspace_service",
    "get_knowledge_workspace_service",
]
