from __future__ import annotations

from backend.core import get_logger


logger = get_logger("agent.runtime")


def log_agent_event(event: str, metadata: dict | None = None):
    logger.info(
        "event=%s metadata=%s",
        event,
        metadata or {},
    )
