from __future__ import annotations

from backend.core import get_logger


logger = get_logger("rag.pipeline")


def log_rag_event(
    event: str,
    query: str | None = None,
    metadata: dict | None = None,
):
    logger.info(
        "event=%s query=%s metadata=%s",
        event,
        query,
        metadata or {},
    )
