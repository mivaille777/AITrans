from __future__ import annotations

from threading import Lock

from app.research.memory import ResearchMemoryStore
from backend.api.dependencies import (
    get_research_note_service,
    get_research_workspace_service,
)
from backend.services.research_memory_extraction_service import (
    ResearchMemoryExtractionService,
)
from backend.services.research_memory_service import ResearchMemoryService

_research_memory_service: ResearchMemoryService | None = None
_research_memory_service_lock = Lock()


def get_research_memory_service() -> ResearchMemoryService:
    global _research_memory_service
    if _research_memory_service is not None:
        return _research_memory_service
    with _research_memory_service_lock:
        if _research_memory_service is None:
            _research_memory_service = ResearchMemoryService(
                ResearchMemoryStore(),
                research_note_service=get_research_note_service(),
                workspace_service=get_research_workspace_service(),
                extraction_service=ResearchMemoryExtractionService(),
            )
        return _research_memory_service


def close_research_memory_service() -> None:
    global _research_memory_service
    with _research_memory_service_lock:
        service = _research_memory_service
        _research_memory_service = None
    if service is not None:
        service.close()


__all__ = [
    "close_research_memory_service",
    "get_research_memory_service",
]
