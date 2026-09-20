"""Runtime-configurable, code-owned LLM routing for AITranslator workloads."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any

from app.ai.client import (
    DEFAULT_DEEPSEEK_MODEL,
    SUPPORTED_DEEPSEEK_MODELS,
    DeepSeekClient,
)
from app.ai.errors import AIConfigurationError
from app.ai.factory import (
    DEFAULT_AI_PROVIDER,
    is_openai_compatible_provider,
    normalize_ai_provider,
    provider_defaults,
)
from app.ai.models import AITextRequest, AITextResult
from app.ai.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleTextProvider,
)
from app.ai.provider import DeepSeekTextProvider
from app.ai.runtime_status import llm_runtime_status
from app.ai.service import AITextService
from app.infrastructure.settings import SettingsManager


@dataclass(frozen=True, slots=True)
class LLMRoute:
    role: str
    provider: str
    model: str
    base_url: str = ""
    thinking_enabled: bool = False


_DEFAULT_MODELS = {
    "planner": "deepseek-v4-flash",
    "agent_synthesis": "deepseek-v4-pro",
    "reading": "deepseek-v4-pro",
    "academic_writer": "deepseek-v4-pro",
    "translation_ai": DEFAULT_DEEPSEEK_MODEL,
    "polish": DEFAULT_DEEPSEEK_MODEL,
}
_ENV_BY_ROLE = {
    "planner": "AITRANS_MODEL_PLANNER",
    "agent_synthesis": "AITRANS_MODEL_AGENT_SYNTHESIS",
    "reading": "AITRANS_MODEL_READING",
    "academic_writer": "AITRANS_MODEL_ACADEMIC_WRITER",
    "translation_ai": "AITRANS_MODEL_TRANSLATION_AI",
    "polish": "AITRANS_MODEL_POLISH",
}


class RoutedAITextService:
    """Lazy AITextService facade bound to one saved provider configuration."""

    def __init__(self, route: LLMRoute) -> None:
        self.route = route
        self._service: AITextService | None = None
        self._lock = RLock()

    def _ensure(self) -> AITextService:
        if self._service is not None:
            return self._service
        with self._lock:
            if self._service is None:
                route_key = "|".join(
                    (
                        self.route.provider,
                        self.route.model,
                        self.route.base_url.rstrip("/"),
                    )
                )
                try:
                    if self.route.provider == DEFAULT_AI_PROVIDER:
                        client = DeepSeekClient(
                            model=self.route.model,
                            thinking_enabled=self.route.thinking_enabled,
                        )
                        provider = DeepSeekTextProvider(client=client)
                    elif is_openai_compatible_provider(self.route.provider):
                        client = OpenAICompatibleClient(
                            provider=self.route.provider,
                            model=self.route.model,
                            base_url=self.route.base_url,
                        )
                        provider = OpenAICompatibleTextProvider(
                            client=client,
                            name=self.route.provider,
                        )
                    else:  # Defensive: routes are validated by LLMGateway.
                        raise AIConfigurationError(
                            f"Unsupported saved AI provider: {self.route.provider}."
                        )
                    self._service = AITextService(provider)
                except AIConfigurationError as exc:
                    llm_runtime_status.mark_unavailable(
                        provider=self.route.provider,
                        model=self.route.model,
                        route_key=route_key,
                        detail=str(exc),
                    )
                    raise
            return self._service

    @property
    def provider_name(self) -> str:
        return self.route.provider

    @property
    def model(self) -> str:
        return self.route.model

    @property
    def provider(self) -> Any:
        return self._ensure().provider

    def execute(self, request: AITextRequest) -> AITextResult:
        return self._ensure().execute(request)

    def translate(self, *args: Any, **kwargs: Any) -> AITextResult:
        return self._ensure().translate(*args, **kwargs)

    def polish(self, *args: Any, **kwargs: Any) -> AITextResult:
        return self._ensure().polish(*args, **kwargs)

    def close(self) -> None:
        with self._lock:
            service = self._service
            self._service = None
        if service is not None:
            service.close()


class LLMGateway:
    """Resolve safe, persisted provider settings for every product LLM role.

    Provider selection is local user configuration. Prompt and role ownership
    remain code-owned; environment role overrides are retained for development
    and deployment diagnostics only.
    """

    def __init__(
        self,
        *,
        settings_factory: Callable[[], Any] = SettingsManager,
    ) -> None:
        self._settings_factory = settings_factory

    @staticmethod
    def _config_value(config: Any, key: str, default: str) -> str:
        get = getattr(config, "get", None)
        if not callable(get):
            return default
        return str(get("ai", key, default) or default).strip()

    @staticmethod
    def _has_saved_user_value(config: Any, key: str) -> bool:
        """Distinguish shipped defaults from an explicit settings-page save."""

        user_data = getattr(config, "user_data", None)
        if user_data is None:
            # Test and integration config adapters conventionally expose only
            # effective values, which should be treated as deliberate input.
            return True
        ai_values = user_data.get("ai") if isinstance(user_data, Mapping) else None
        return isinstance(ai_values, Mapping) and key in ai_values

    def route(self, role: str) -> LLMRoute:
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in _DEFAULT_MODELS:
            raise AIConfigurationError(
                f"Unsupported LLM route role: {normalized_role or '<empty>'}."
            )

        settings = self._settings_factory()
        provider = normalize_ai_provider(
            self._config_value(settings, "provider", DEFAULT_AI_PROVIDER)
        )
        default_model, default_base_url = provider_defaults(provider)
        configured_model = self._config_value(settings, "model", default_model)
        configured_base_url = self._config_value(settings, "base_url", default_base_url)
        environment_model = os.getenv(_ENV_BY_ROLE[normalized_role], "").strip()
        saved_model = self._has_saved_user_value(settings, "model")
        model = environment_model or (
            configured_model if saved_model else _DEFAULT_MODELS[normalized_role]
        )

        if provider == DEFAULT_AI_PROVIDER and environment_model and model not in SUPPORTED_DEEPSEEK_MODELS:
            supported = ", ".join(sorted(SUPPORTED_DEEPSEEK_MODELS))
            raise AIConfigurationError(
                f"Unsupported model for DeepSeek LLM route {normalized_role}: "
                f"{model}. Supported environment overrides: {supported}."
            )
        if provider == DEFAULT_AI_PROVIDER and not model:
            raise AIConfigurationError("DeepSeek provider requires a model identifier.")
        if is_openai_compatible_provider(provider) and not model:
            raise AIConfigurationError("The selected AI provider requires a model identifier.")
        if is_openai_compatible_provider(provider) and not configured_base_url:
            raise AIConfigurationError("The selected AI provider requires a base URL.")

        return LLMRoute(
            role=normalized_role,
            provider=provider,
            model=model,
            base_url=configured_base_url,
            thinking_enabled=False,
        )

    def create_text_service(self, role: str) -> RoutedAITextService:
        return RoutedAITextService(self.route(role))

    def describe_routes(self) -> tuple[LLMRoute, ...]:
        return tuple(self.route(role) for role in _DEFAULT_MODELS)


__all__ = ["LLMGateway", "LLMRoute", "RoutedAITextService"]
