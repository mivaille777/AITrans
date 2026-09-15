from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import AIConfigurationError
from app.ai.gateway import LLMRoute, RoutedAITextService
from app.ai.runtime_status import (
    LLMRuntimeStatus,
    llm_runtime_status,
    track_llm_request,
)
from backend.main import create_app
from backend.services.llm_status_service import LLMStatusService


class _Gateway:
    def route(self, role: str) -> LLMRoute:
        assert role == "reading"
        return LLMRoute(
            role=role,
            provider="openai_compatible",
            model="test-model",
            base_url="http://localhost:11434/v1",
        )

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


def test_status_service_accepts_valid_config_without_a_separate_api_probe() -> None:
    gateway = _Gateway()
    service = LLMStatusService(gateway=gateway)  # type: ignore[arg-type]

    current = service.status()

    assert current.state == "available"
    assert current.provider == "openai_compatible"
    assert current.model == "test-model"


def test_status_service_preserves_a_real_request_failure() -> None:
    service = LLMStatusService(gateway=_Gateway())  # type: ignore[arg-type]
    assert service.status().state == "available"

    with pytest.raises(RuntimeError), track_llm_request(
        provider="openai_compatible",
        model="test-model",
        route_key="openai_compatible|test-model|http://localhost:11434/v1",
    ):
        raise RuntimeError("network failed")

    assert service.status().state == "unavailable"


def test_client_initialization_failure_marks_status_unavailable(monkeypatch) -> None:
    from app.ai import gateway as gateway_module

    def fail_client(**_kwargs):
        raise AIConfigurationError("API key is unavailable.")

    monkeypatch.setattr(gateway_module, "DeepSeekClient", fail_client)
    service = RoutedAITextService(
        LLMRoute(
            role="reading",
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
        )
    )

    with pytest.raises(AIConfigurationError, match="API key"):
        _ = service.provider

    snapshot = llm_runtime_status.snapshot()
    assert snapshot.state == "unavailable"
    assert snapshot.detail == "API key is unavailable."


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
