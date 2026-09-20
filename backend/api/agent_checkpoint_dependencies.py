from __future__ import annotations

from threading import Lock

from backend.services.agent_checkpoint_service import AgentCheckpointService

_agent_checkpoint_service: AgentCheckpointService | None = None
_agent_checkpoint_service_lock = Lock()


def get_agent_checkpoint_service() -> AgentCheckpointService:
    global _agent_checkpoint_service
    if _agent_checkpoint_service is not None:
        return _agent_checkpoint_service

    with _agent_checkpoint_service_lock:
        if _agent_checkpoint_service is None:
            _agent_checkpoint_service = AgentCheckpointService()
        return _agent_checkpoint_service


def close_agent_checkpoint_service() -> None:
    global _agent_checkpoint_service
    with _agent_checkpoint_service_lock:
        service = _agent_checkpoint_service
        _agent_checkpoint_service = None
    if service is not None:
        service.close()


__all__ = ["close_agent_checkpoint_service", "get_agent_checkpoint_service"]
