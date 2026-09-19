from __future__ import annotations

from app.ai.factory import create_ai_text_service
from app.ai.openai_compatible import OpenAICompatibleTextProvider
from app.ai.provider import DeepSeekTextProvider


class FakeConfig:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, section: str, key: str, default=None):
        if section != "ai":
            return default
        return self.values.get(key, default)


class FakeCredentialStore:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, provider: str):
        return self.values.get(provider)


def test_factory_builds_saved_deepseek_provider_and_model() -> None:
    config = FakeConfig(
        {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
        }
    )
    store = FakeCredentialStore({"deepseek": "sk-test"})

    service = create_ai_text_service(config, credential_store=store)
    try:
        assert isinstance(service.provider, DeepSeekTextProvider)
        assert service.provider_name == "deepseek"
        assert service.model == "deepseek-v4-pro"
    finally:
        service.close()


def test_factory_builds_saved_openai_compatible_provider() -> None:
    config = FakeConfig(
        {
            "provider": "openai_compatible",
            "model": "custom-model-v1",
            "base_url": "https://example.invalid/v1",
        }
    )
    store = FakeCredentialStore({"openai_compatible": "custom-secret"})

    service = create_ai_text_service(config, credential_store=store)
    try:
        assert isinstance(service.provider, OpenAICompatibleTextProvider)
        assert service.provider_name == "openai_compatible"
        assert service.model == "custom-model-v1"
        assert service.provider.client.base_url == "https://example.invalid/v1"
    finally:
        service.close()


def test_factory_builds_openai_protocol_provider_preset() -> None:
    config = FakeConfig({"provider": "groq"})
    store = FakeCredentialStore({"groq": "groq-secret"})

    service = create_ai_text_service(config, credential_store=store)
    try:
        assert isinstance(service.provider, OpenAICompatibleTextProvider)
        assert service.provider_name == "groq"
        assert service.model == "llama-3.3-70b-versatile"
        assert service.provider.client.base_url == "https://api.groq.com/openai/v1"
    finally:
        service.close()
