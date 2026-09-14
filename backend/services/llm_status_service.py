"""Cached connectivity checks and runtime activity for the configured LLM."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.ai.errors import AIError
from app.ai.gateway import LLMGateway, LLMRoute
from app.ai.runtime_status import llm_runtime_status

PROBE_MAX_AGE_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class LLMStatus:
    state: str
    provider: str
    model: str
    detail: str
    active_requests: int


class LLMStatusService:
    _probe_lock = Lock()

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._gateway = gateway or LLMGateway()

    @staticmethod
    def _route_key(route: LLMRoute) -> str:
        return "|".join((route.provider, route.model, route.base_url.rstrip("/")))

    def status(self) -> LLMStatus:
        try:
            route = self._gateway.route("reading")
        except AIError as exc:
            llm_runtime_status.record_probe(
                success=False,
                provider="",
                model="",
                route_key="configuration-error",
                detail=str(exc),
            )
            return self._snapshot()

        route_key = self._route_key(route)
        if llm_runtime_status.needs_probe(
            route_key,
            max_age_seconds=PROBE_MAX_AGE_SECONDS,
        ):
            self._probe(route, route_key)
        return self._snapshot()

    def _probe(self, route: LLMRoute, route_key: str) -> None:
        with self._probe_lock:
            if not llm_runtime_status.needs_probe(
                route_key,
                max_age_seconds=PROBE_MAX_AGE_SECONDS,
            ):
                return
            service = None
            try:
                service = self._gateway.create_text_service("reading")
                client = getattr(service.provider, "client", None)
                probe = getattr(client, "probe", None)
                if not callable(probe):
                    raise TypeError("The selected LLM provider cannot be checked.")
                probe()
            except AIError as exc:
                llm_runtime_status.record_probe(
                    success=False,
                    provider=route.provider,
                    model=route.model,
                    route_key=route_key,
                    detail=str(exc),
                )
            except (AttributeError, TypeError):
                llm_runtime_status.record_probe(
                    success=False,
                    provider=route.provider,
                    model=route.model,
                    route_key=route_key,
                    detail="Unable to reach the configured LLM API.",
                )
            else:
                llm_runtime_status.record_probe(
                    success=True,
                    provider=route.provider,
                    model=route.model,
                    route_key=route_key,
                )
            finally:
                if service is not None:
                    service.close()

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


__all__ = ["PROBE_MAX_AGE_SECONDS", "LLMStatus", "LLMStatusService"]
