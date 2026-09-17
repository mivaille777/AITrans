from __future__ import annotations

from threading import Lock

from app.infrastructure.paths import writable_config_dir
from backend.agent_core.orchestration import build_artifact_store
from backend.api.dependencies import (
    get_research_note_service,
    get_research_workspace_service,
)
from backend.api.knowledge_workspace_dependencies import (
    DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME,
    get_knowledge_workspace_service,
)
from backend.api.memory_dependencies import get_memory_coordinator
from backend.knowledge.suggestion_repository import (
    SqliteKnowledgeRelationSuggestionRepository,
)
from backend.services.curator_commit_service import CuratorCommitService

_service: CuratorCommitService | None = None
_lock = Lock()


def get_curator_commit_service() -> CuratorCommitService:
    global _service
    if _service is not None:
        return _service
    with _lock:
        if _service is None:
            database_path = writable_config_dir() / DEFAULT_KNOWLEDGE_WORKSPACE_FILENAME
            _service = CuratorCommitService(
                artifact_store=build_artifact_store(),
                knowledge_workspace=get_knowledge_workspace_service(),
                suggestion_repository=SqliteKnowledgeRelationSuggestionRepository(
                    database_path
                ),
                research_notes=get_research_note_service(),
                research_workspaces=get_research_workspace_service(),
                memory_coordinator=get_memory_coordinator(),
                database_path=database_path,
            )
        return _service


def close_curator_commit_service() -> None:
    global _service
    with _lock:
        _service = None


__all__ = ["close_curator_commit_service", "get_curator_commit_service"]
