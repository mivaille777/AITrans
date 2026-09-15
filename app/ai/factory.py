"""Build the configured AI text service from persisted provider preferences."""

from __future__ import annotations

from typing import Any

from app.ai.client import (
    DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DeepSeekClient,
)
from app.ai.errors import AIConfigurationError
from app.ai.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleTextProvider,
)
from app.ai.provider import DeepSeekTextProvider
from app.ai.secrets import ProviderCredentialStore
from app.ai.service import AITextService

DEFAULT_AI_PROVIDER = "deepseek"
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
SUPPORTED_AI_PROVIDERS = (
    DEFAULT_AI_PROVIDER,
    OPENAI_COMPATIBLE_PROVIDER,
)
AI_PROVIDER_LABELS = {
    DEFAULT_AI_PROVIDER: "DeepSeek",
    OPENAI_COMPATIBLE_PROVIDER: "OpenAI-compatible / 自定义",
}


def normalize_ai_provider(value: object) -> str:
    candidate = str(value).strip().lower().replace("-", "_")
    if candidate not in SUPPORTED_AI_PROVIDERS:
        return DEFAULT_AI_PROVIDER
    return candidate


def provider_defaults(provider: object) -> tuple[str, str]:
    normalized = normalize_ai_provider(provider)
    if normalized == DEFAULT_AI_PROVIDER:
        return DEFAULT_DEEPSEEK_MODEL, DEEPSEEK_BASE_URL
    return "", ""


def _config_value(config_manager: Any, key: str, default: str) -> str:
    get = getattr(config_manager, "get", None)
    if not callable(get):
        return default
    return str(get("ai", key, default) or default).strip()


def create_ai_text_service(
    config_manager: Any,
    *,
    credential_store: ProviderCredentialStore | Any | None = None,
) -> AITextService:
    """Create the selected provider using non-secret TOML + secure local key."""

    provider = normalize_ai_provider(
        _config_value(config_manager, "provider", DEFAULT_AI_PROVIDER)
    )
    default_model, default_base_url = provider_defaults(provider)
    model = _config_value(config_manager, "model", default_model)
    base_url = _config_value(config_manager, "base_url", default_base_url)

    if provider == DEFAULT_AI_PROVIDER:
        client = DeepSeekClient(
            model=model or DEFAULT_DEEPSEEK_MODEL,
            credential_store=credential_store,
        )
        return AITextService(
            provider=DeepSeekTextProvider(client=client),
        )

    if not model:
        raise AIConfigurationError(
            "OpenAI-compatible provider requires a model identifier."
        )
    if not base_url:
        raise AIConfigurationError(
            "OpenAI-compatible provider requires a base URL."
        )
    client = OpenAICompatibleClient(
        model=model,
        base_url=base_url,
        credential_store=credential_store,
    )
    return AITextService(
        provider=OpenAICompatibleTextProvider(client=client),
    )


__all__ = [
    "AI_PROVIDER_LABELS",
    "DEFAULT_AI_PROVIDER",
    "OPENAI_COMPATIBLE_PROVIDER",
    "SUPPORTED_AI_PROVIDERS",
    "create_ai_text_service",
    "normalize_ai_provider",
    "provider_defaults",
]
