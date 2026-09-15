"""Local-only API for non-secret active LLM provider configuration."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status

from app.ai.client import SUPPORTED_DEEPSEEK_MODELS
from app.ai.factory import (
    AI_PROVIDER_LABELS,
    DEFAULT_AI_PROVIDER,
    OPENAI_COMPATIBLE_PROVIDER,
    SUPPORTED_AI_PROVIDERS,
    provider_defaults,
)
from app.ai.runtime_status import llm_runtime_status
from app.infrastructure.settings import SettingsManager
from backend.api.dependencies import (
    close_agent_tool_registry,
    close_companion_chat_service,
    close_product_agent_service,
    close_quick_action_service,
)
from backend.api.llm_dependencies import reset_llm_dependencies
from backend.models.llm_settings import (
    LLMProviderOption,
    LLMRuntimeStatusResponse,
    LLMSettingsResponse,
    LLMSettingsUpdateRequest,
)
from backend.services.llm_status_service import LLMStatusService

router = APIRouter(prefix="/api/settings/llm", tags=["settings"])


def _config_value(settings: SettingsManager, key: str, default: str) -> str:
    return str(settings.get("ai", key, default) or default).strip()


def _provider_options() -> list[LLMProviderOption]:
    options: list[LLMProviderOption] = []
    for provider in SUPPORTED_AI_PROVIDERS:
        model, base_url = provider_defaults(provider)
        options.append(
            LLMProviderOption(
                id=provider,
                label=AI_PROVIDER_LABELS[provider],
                requires_base_url=provider == OPENAI_COMPATIBLE_PROVIDER,
                default_model=model,
                default_base_url=base_url,
            )
        )
    return options


def _response(settings: SettingsManager) -> LLMSettingsResponse:
    provider = _config_value(settings, "provider", DEFAULT_AI_PROVIDER)
    if provider not in SUPPORTED_AI_PROVIDERS:
        provider = DEFAULT_AI_PROVIDER
    default_model, default_base_url = provider_defaults(provider)
    return LLMSettingsResponse(
        provider=provider,
        model=_config_value(settings, "model", default_model),
        base_url=_config_value(settings, "base_url", default_base_url),
        providers=_provider_options(),
    )


def _validate(payload: LLMSettingsUpdateRequest) -> tuple[str, str, str]:
    provider = payload.provider
    model = payload.model.strip()
    base_url = payload.base_url.strip()
    if provider == DEFAULT_AI_PROVIDER:
        if model not in SUPPORTED_DEEPSEEK_MODELS:
            raise ValueError("请选择受支持的 DeepSeek 模型。")
        _, default_base_url = provider_defaults(provider)
        return provider, model, base_url or default_base_url
    if not base_url:
        raise ValueError("自定义 OpenAI-compatible 供应商需要 Base URL。")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是完整的 http:// 或 https:// 地址。")
    return provider, model, base_url.rstrip("/")


def _refresh_runtime() -> None:
    # All affected factories are recreated lazily for the next request. This
    # avoids a backend restart while never exposing a credential to the client.
    close_product_agent_service()
    close_agent_tool_registry()
    close_quick_action_service()
    close_companion_chat_service()
    reset_llm_dependencies()
    llm_runtime_status.reset()


@router.get("", response_model=LLMSettingsResponse)
def get_llm_settings() -> LLMSettingsResponse:
    return _response(SettingsManager())


@router.get("/status", response_model=LLMRuntimeStatusResponse)
def get_llm_runtime_status() -> LLMRuntimeStatusResponse:
    current = LLMStatusService().status()
    return LLMRuntimeStatusResponse(
        state=current.state,
        provider=current.provider,
        model=current.model,
        detail=current.detail,
        active_requests=current.active_requests,
    )


@router.put("", response_model=LLMSettingsResponse)
def update_llm_settings(payload: LLMSettingsUpdateRequest) -> LLMSettingsResponse:
    try:
        provider, model, base_url = _validate(payload)

        settings = SettingsManager()
        settings.save({"ai": {"provider": provider, "model": model, "base_url": base_url}})

        _refresh_runtime()
        return _response(SettingsManager())
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


__all__ = ["router"]
