from __future__ import annotations

from threading import Lock

from app.infrastructure.paths import writable_config_dir
from backend.api.knowledge_workspace_dependencies import DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME
from backend.knowledge.v2_repository import KnowledgeV2Repository
from backend.knowledge.v2_service import KnowledgeV2Service

_service: KnowledgeV2Service | None = None
_service_lock = Lock()


def get_knowledge_v2_service() -> KnowledgeV2Service:
    """Return the legacy V2 API adapter over the canonical knowledge database."""

    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            repository = KnowledgeV2Repository(
                writable_config_dir() / DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME
            )
            _service = KnowledgeV2Service(repository)
        return _service


def close_knowledge_v2_service() -> None:
    global _service
    with _service_lock:
        _service = None


__all__ = ["close_knowledge_v2_service", "get_knowledge_v2_service"]
