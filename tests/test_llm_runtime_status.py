from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.gateway import LLMRoute
from app.ai.runtime_status import (
    LLMRuntimeStatus,
    llm_runtime_status,
    track_llm_request,
)
from backend.main import create_app
from backend.services.llm_status_service import LLMStatusService


class _ProbeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def probe(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class _TextService:
    def __init__(self, client: _ProbeClient) -> None:
        self.provider = SimpleNamespace(client=client)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Gateway:
    def __init__(self, client: _ProbeClient) -> None:
        self.client = client
        self.services: list[_TextService] = []

    def route(self, role: str) -> LLMRoute:
        assert role == "reading"
        return LLMRoute(
            role=role,
            provider="openai_compatible",
            model="test-model",
            base_url="http://localhost:11434/v1",
        )

    def create_text_service(self, role: str) -> _TextService:
        assert role == "reading"
        service = _TextService(self.client)
        self.services.append(service)
        return service


@pytest.fixture(autouse=True)
def _reset_global_status():
    llm_runtime_status.reset()
    yield
    llm_runtime_status.reset()


def test_runtime_tracker_exposes_calling_then_available() -> None:
    tracker = LLMRuntimeStatus()
    tracker.begin(provider="deepseek", model="model", route_key="route")
    assert tracker.snapshot().state == "calling"

    tracker.finish(
        success=True,
        provider="deepseek",
        model="model",
        route_key="route",
    )
    assert tracker.snapshot().state == "available"


def test_request_failure_marks_runtime_unavailable_without_leaking_details() -> None:
    with (
        pytest.raises(RuntimeError, match="secret provider detail"),
        track_llm_request(
            provider="deepseek",
            model="model",
            route_key="route",
        ),
    ):
        raise RuntimeError("secret provider detail")

    snapshot = llm_runtime_status.snapshot()
    assert snapshot.state == "unavailable"
    assert snapshot.detail == "LLM API request failed."


def test_status_service_probes_once_and_caches_success() -> None:
    client = _ProbeClient()
    gateway = _Gateway(client)
    service = LLMStatusService(gateway=gateway)  # type: ignore[arg-type]

    first = service.status()
    second = service.status()

    assert first.state == "available"
    assert second.state == "available"
    assert client.calls == 1
    assert gateway.services[0].closed is True


def test_status_api_returns_runtime_contract(monkeypatch) -> None:
    from backend.api import llm_settings

    current = SimpleNamespace(
        state="calling",
        provider="deepseek",
        model="deepseek-v4-flash",
        detail="",
        active_requests=2,
    )
    monkeypatch.setattr(
        llm_settings,
        "LLMStatusService",
        lambda: SimpleNamespace(status=lambda: current),
    )

    response = TestClient(create_app()).get("/api/settings/llm/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "calling",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "detail": "",
        "active_requests": 2,
    }
