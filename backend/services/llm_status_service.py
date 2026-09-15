"""Expose configured LLM state and real request activity."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.errors import AIError
from app.ai.gateway import LLMGateway
from app.ai.runtime_status import llm_runtime_status


@dataclass(frozen=True, slots=True)
class LLMStatus:
    state: str
    provider: str
    model: str
    detail: str
    active_requests: int


class LLMStatusService:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._gateway = gateway or LLMGateway()

    def status(self) -> LLMStatus:
        try:
            route = self._gateway.route("reading")
        except AIError as exc:
            llm_runtime_status.mark_unavailable(
                provider="",
                model="",
                route_key="configuration-error",
                detail=str(exc),
            )
            return self._snapshot()

        route_key = "|".join(
            (route.provider, route.model, route.base_url.rstrip("/"))
        )
        # A separate /models probe can fail on an otherwise working compatible
        # provider. Real completion calls are the source of connectivity truth.
        llm_runtime_status.configure(
            provider=route.provider,
            model=route.model,
            route_key=route_key,
        )
        return self._snapshot()

    @staticmethod
    def _snapshot() -> LLMStatus:
        snapshot = llm_runtime_status.snapshot()
        return LLMStatus(
            state=snapshot.state,
            provider=snapshot.provider,
            model=snapshot.model,
            detail=snapshot.detail,
            active_requests=snapshot.active_requests,
        )


__all__ = ["LLMStatus", "LLMStatusService"]
