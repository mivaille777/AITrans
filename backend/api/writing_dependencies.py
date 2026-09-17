from __future__ import annotations

from threading import Lock

from backend.agent_core.orchestration import build_artifact_store
from backend.api.dependencies import get_research_workspace_service
from backend.api.memory_dependencies import get_memory_coordinator
from backend.services.writing_project_service import WritingProjectService

_service: WritingProjectService | None = None
_service_lock = Lock()


def get_writing_project_service() -> WritingProjectService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            store = build_artifact_store()
            _service = WritingProjectService(
                artifact_store=store,
                workspace_service=get_research_workspace_service(),
                memory_coordinator=get_memory_coordinator(),
            )
        return _service


def close_writing_project_service() -> None:
    global _service
    with _service_lock:
        _service = None


__all__ = ["close_writing_project_service", "get_writing_project_service"]
