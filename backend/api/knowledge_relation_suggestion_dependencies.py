from __future__ import annotations

from threading import Lock

from app.infrastructure.paths import writable_config_dir
from backend.api.knowledge_workspace_dependencies import (
    DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME,
    get_knowledge_workspace_service,
)
from backend.api.llm_dependencies import get_llm_gateway
from backend.knowledge.suggestion_repository import (
    SqliteKnowledgeRelationSuggestionRepository,
)
from backend.services.knowledge_relation_suggestion_service import (
    KnowledgeRelationSuggestionService,
)

_service: KnowledgeRelationSuggestionService | None = None
_service_lock = Lock()


def get_knowledge_relation_suggestion_service() -> KnowledgeRelationSuggestionService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            workspace = get_knowledge_workspace_service()
            storage_path = writable_config_dir() / DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME
            repository = SqliteKnowledgeRelationSuggestionRepository(storage_path)
            text_service = get_llm_gateway().create_text_service("planner")
            _service = KnowledgeRelationSuggestionService(
                workspace=workspace,
                repository=repository,
                text_service=text_service,
            )
        return _service


def close_knowledge_relation_suggestion_service() -> None:
    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        service.close()


__all__ = [
    "close_knowledge_relation_suggestion_service",
    "get_knowledge_relation_suggestion_service",
]
