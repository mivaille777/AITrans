from __future__ import annotations

from typing import ClassVar

from fastapi.testclient import TestClient

from backend.main import create_app


class _FakeSettings:
    values: ClassVar[dict[str, str]] = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
    }
    saved: ClassVar[list[dict[str, object]]] = []

    def get(self, section: str, key: str, default=None):
        assert section == "ai"
        return self.values.get(key, default)

    def save(self, payload: dict[str, dict[str, str]]):
        self.values.update(payload["ai"])
        self.saved.append(payload)
        return {"ai": dict(self.values)}


def test_llm_settings_api_persists_non_secret_config(monkeypatch) -> None:
    from backend.api import llm_settings

    _FakeSettings.values = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
    }
    _FakeSettings.saved = []
    monkeypatch.setattr(llm_settings, "SettingsManager", _FakeSettings)
    monkeypatch.setattr(llm_settings, "_refresh_runtime", lambda: None)
    client = TestClient(create_app())

    response = client.put(
        "/api/settings/llm",
        json={
            "provider": "openai_compatible",
            "model": "gpt-test",
            "base_url": "https://gateway.example/v1/",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai_compatible"
    assert body["model"] == "gpt-test"
    assert body["base_url"] == "https://gateway.example/v1"
    assert _FakeSettings.saved[-1]["ai"] == {
        "provider": "openai_compatible",
        "model": "gpt-test",
        "base_url": "https://gateway.example/v1",
    }


def test_llm_settings_api_lists_provider_presets(monkeypatch) -> None:
    from backend.api import llm_settings

    _FakeSettings.values = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
    }
    monkeypatch.setattr(llm_settings, "SettingsManager", _FakeSettings)
    client = TestClient(create_app())

    response = client.get("/api/settings/llm")

    assert response.status_code == 200
    providers = response.json()["providers"]
    assert [provider["id"] for provider in providers] == [
        "deepseek",
        "openai",
        "google",
        "mistral",
        "groq",
        "openrouter",
        "together",
        "qwen",
        "openai_compatible",
    ]


def test_llm_settings_api_requires_valid_custom_base_url(monkeypatch) -> None:
    from backend.api import llm_settings

    monkeypatch.setattr(llm_settings, "SettingsManager", _FakeSettings)
    monkeypatch.setattr(llm_settings, "_refresh_runtime", lambda: None)
    client = TestClient(create_app())

    response = client.put(
        "/api/settings/llm",
        json={
            "provider": "openai_compatible",
            "model": "gpt-test",
            "base_url": "localhost:11434",
        },
    )

    assert response.status_code == 422
    assert "Base URL" in response.json()["detail"]


def test_llm_settings_api_rejects_key_fields(monkeypatch) -> None:
    from backend.api import llm_settings

    monkeypatch.setattr(llm_settings, "SettingsManager", _FakeSettings)
    monkeypatch.setattr(llm_settings, "_refresh_runtime", lambda: None)
    client = TestClient(create_app())

    response = client.put(
        "/api/settings/llm",
        json={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "api_key": "must-be-rejected",
        },
    )

    assert response.status_code == 422
    assert "Extra inputs" in response.text


def test_llm_models_api_returns_models_from_current_provider(monkeypatch) -> None:
    from backend.api import llm_settings

    _FakeSettings.values = {
        "provider": "openai_compatible",
        "model": "llama-current",
        "base_url": "https://gateway.example/v1",
    }
    monkeypatch.setattr(llm_settings, "SettingsManager", _FakeSettings)
    monkeypatch.setattr(
        llm_settings,
        "list_available_model_ids",
        lambda **_: ("llama-current", "llama-fast"),
    )
    client = TestClient(create_app())

    response = client.get("/api/settings/llm/models")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai_compatible",
        "current_model": "llama-current",
        "available": True,
        "models": [{"id": "llama-current"}, {"id": "llama-fast"}],
        "detail": "",
    }
