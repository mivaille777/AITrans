from __future__ import annotations

from backend.core import get_logger


logger = get_logger("llm.call")


def log_llm_call(
    provider: str,
    model: str | None,
    latency: float,
    tokens: int | None = None,
    success: bool = True,
):
    logger.info(
        "provider=%s model=%s latency=%.3fs tokens=%s success=%s",
        provider,
        model,
        latency,
        tokens,
        success,
    )
