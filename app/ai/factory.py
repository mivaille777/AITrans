"""Build the configured AI text service from persisted provider preferences."""

from __future__ import annotations

from typing import Any

from app.ai.client import (
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
OPENAI_COMPATIBLE_PROVIDER_IDS = (
    "openai",
    "google",
    "mistral",
    "groq",
    "openrouter",
    "together",
    "qwen",
    OPENAI_COMPATIBLE_PROVIDER,
)
SUPPORTED_AI_PROVIDERS = (DEFAULT_AI_PROVIDER, *OPENAI_COMPATIBLE_PROVIDER_IDS)
AI_PROVIDER_LABELS = {
    DEFAULT_AI_PROVIDER: "DeepSeek",
    "openai": "OpenAI",
    "google": "Google Gemini",
    "mistral": "Mistral",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "together": "Together AI",
    "qwen": "Qwen",
    OPENAI_COMPATIBLE_PROVIDER: "OpenAI-compatible / 自定义",
}
_PROVIDER_DEFAULTS = {
    DEFAULT_AI_PROVIDER: ("deepseek-v4-flash", "https://api.deepseek.com"),
    "openai": ("gpt-4o-mini", "https://api.openai.com/v1"),
    "google": ("gemini-2.0-flash", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "mistral": ("mistral-small-latest", "https://api.mistral.ai/v1"),
    "groq": ("llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
    "openrouter": ("openai/gpt-4o-mini", "https://openrouter.ai/api/v1"),
    "together": ("meta-llama/Llama-3.3-70B-Instruct-Turbo", "https://api.together.xyz/v1"),
    "qwen": ("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    OPENAI_COMPATIBLE_PROVIDER: ("", ""),
}


def normalize_ai_provider(value: object) -> str:
    candidate = str(value).strip().lower().replace("-", "_")
    if candidate not in SUPPORTED_AI_PROVIDERS:
        return DEFAULT_AI_PROVIDER
    return candidate


def provider_defaults(provider: object) -> tuple[str, str]:
    normalized = normalize_ai_provider(provider)
    return _PROVIDER_DEFAULTS[normalized]


def is_openai_compatible_provider(provider: object) -> bool:
    normalized = str(provider or "").strip().lower().replace("-", "_")
    return normalized in OPENAI_COMPATIBLE_PROVIDER_IDS


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
        text_provider = DeepSeekTextProvider(client=client)
    elif is_openai_compatible_provider(provider):
        if not model:
            raise AIConfigurationError(
                f"{AI_PROVIDER_LABELS[provider]} requires a model identifier."
            )
        if not base_url:
            raise AIConfigurationError(
                f"{AI_PROVIDER_LABELS[provider]} requires a Base URL."
            )
        client = OpenAICompatibleClient(
            provider=provider,
            model=model,
            base_url=base_url,
            credential_store=credential_store,
        )
        text_provider = OpenAICompatibleTextProvider(client=client, name=provider)
    else:  # Defensive: normalize_ai_provider() keeps this unreachable.
        raise AIConfigurationError(f"Unsupported saved AI provider: {provider}.")

    return AITextService(provider=text_provider)


__all__ = [
    "AI_PROVIDER_LABELS",
    "DEFAULT_AI_PROVIDER",
    "OPENAI_COMPATIBLE_PROVIDER",
    "OPENAI_COMPATIBLE_PROVIDER_IDS",
    "SUPPORTED_AI_PROVIDERS",
    "create_ai_text_service",
    "is_openai_compatible_provider",
    "normalize_ai_provider",
    "provider_defaults",
]
