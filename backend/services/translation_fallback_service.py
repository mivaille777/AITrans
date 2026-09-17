from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.ai.gateway import LLMGateway
from app.infrastructure.settings import SettingsManager
from app.models.translation import TranslationRequest
from app.translation.errors import TextNormalizationError, TranslationError
from app.translation.google_web_provider import GoogleWebTranslationProvider
from app.translation.normalizer import TextNormalizer
from app.translation.youdao_web_provider import YoudaoWebTranslationProvider

TranslationProviderMode = Literal["auto", "youdao_web", "google_web", "ai"]


@dataclass(frozen=True, slots=True)
class TranslationAttempt:
    provider: str
    status: str


@dataclass(frozen=True, slots=True)
class TranslationCascadeResult:
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    provider: str
    model: str
    request_id: int
    fallback_level: int
    notice: str
    attempts: tuple[TranslationAttempt, ...]


class TranslationFallbackService:
    """Request-local translation orchestration.

    ``auto`` preserves the deterministic Youdao -> Google -> AI cascade.
    Explicit provider modes are strict: they never silently fall back to a
    different engine and never mutate the user's persisted provider setting.
    """

    def __init__(
        self,
        *,
        settings_factory: Callable[[], SettingsManager] = SettingsManager,
        llm_gateway: LLMGateway | None = None,
        normalizer: TextNormalizer | None = None,
    ) -> None:
        self._settings_factory = settings_factory
        self._llm_gateway = llm_gateway or LLMGateway()
        self._normalizer = normalizer or TextNormalizer()

    @staticmethod
    def _close_provider(provider: object | None) -> None:
        if provider is None:
            return
        close = getattr(provider, "close", None)
        if callable(close):
            close()

    def _request(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str,
        request_id: int,
    ) -> TranslationRequest:
        normalized = self._normalizer.normalize(source_text)
        return TranslationRequest(
            source_text=normalized,
            source_language=str(source_language or "auto").strip() or "auto",
            target_language=str(target_language or "zh-CN").strip() or "zh-CN",
            request_id=max(0, int(request_id or 0)),
        )

    def _web_provider(self, provider_name: str):
        if provider_name == "youdao_web":
            return YoudaoWebTranslationProvider(config_manager=self._settings_factory())
        if provider_name == "google_web":
            return GoogleWebTranslationProvider(config_manager=self._settings_factory())
        raise ValueError(f"unsupported web translation provider: {provider_name}")

    def _translate_web(
        self,
        provider_name: str,
        request: TranslationRequest,
        *,
        fallback_level: int,
        notice: str = "",
    ) -> TranslationCascadeResult:
        provider = None
        try:
            provider = self._web_provider(provider_name)
            result = provider.translate(request)
            if not result.translated_text.strip():
                raise TranslationError("translated text is empty")
            return TranslationCascadeResult(
                source_text=request.source_text,
                translated_text=result.translated_text,
                source_language=result.source_language,
                target_language=result.target_language,
                provider=result.provider or provider_name,
                model="",
                request_id=request.request_id,
                fallback_level=fallback_level,
                notice=notice,
                attempts=(TranslationAttempt(provider_name, "success"),),
            )
        finally:
            self._close_provider(provider)

    def _translate_ai(
        self,
        request: TranslationRequest,
        *,
        fallback_level: int,
        notice: str = "",
        terminology: tuple[str, ...] = (),
    ) -> TranslationCascadeResult:
        ai_service = None
        try:
            ai_service = self._llm_gateway.create_text_service("translation_ai")
            translate_arguments = {
                "source_language": request.source_language,
                "target_language": request.target_language,
                "request_id": request.request_id,
            }
            if terminology:
                translate_arguments["terminology"] = terminology
            ai_result = ai_service.translate(request.source_text, **translate_arguments)
            if not ai_result.output_text.strip():
                raise TranslationError("AI translated text is empty")
            return TranslationCascadeResult(
                source_text=request.source_text,
                translated_text=ai_result.output_text,
                source_language=ai_result.source_language,
                target_language=ai_result.target_language,
                provider="ai",
                model=ai_result.model,
                request_id=request.request_id,
                fallback_level=fallback_level,
                notice=notice,
                attempts=(TranslationAttempt("ai", "success"),),
            )
        finally:
            if ai_service is not None:
                ai_service.close()

    def translate(
        self,
        source_text: str,
        *,
        source_language: str = "auto",
        target_language: str = "zh-CN",
        request_id: int = 0,
        provider_mode: TranslationProviderMode = "auto",
        terminology: tuple[str, ...] = (),
    ) -> TranslationCascadeResult:
        request = self._request(
            source_text,
            source_language=source_language,
            target_language=target_language,
            request_id=request_id,
        )
        mode = str(provider_mode or "auto").strip().lower()
        if mode not in {"auto", "youdao_web", "google_web", "ai"}:
            raise ValueError(f"unsupported translation provider mode: {provider_mode}")
        normalized_terminology = tuple(
            str(item).strip()[:1000] for item in terminology[:32] if str(item).strip()
        )
        # Public web engines cannot guarantee a caller-provided glossary. Use
        # the AI language capability whenever an effective terminology memory
        # is present instead of falsely reporting that the preference was used.
        if normalized_terminology and mode == "auto":
            mode = "ai"

        if mode == "youdao_web":
            try:
                return self._translate_web("youdao_web", request, fallback_level=0)
            except TextNormalizationError:
                raise
            except Exception as exc:
                raise TranslationError("Youdao translation is unavailable") from exc

        if mode == "google_web":
            try:
                return self._translate_web("google_web", request, fallback_level=0)
            except TextNormalizationError:
                raise
            except Exception as exc:
                raise TranslationError("Google translation is unavailable") from exc

        if mode == "ai":
            try:
                return self._translate_ai(
                    request,
                    fallback_level=0,
                    terminology=normalized_terminology,
                )
            except TextNormalizationError:
                raise
            except Exception as exc:
                raise TranslationError("AI translation is unavailable") from exc

        attempts: list[TranslationAttempt] = []
        for fallback_level, provider_name in enumerate(("youdao_web", "google_web")):
            provider = None
            try:
                provider = self._web_provider(provider_name)
                result = provider.translate(request)
                if not result.translated_text.strip():
                    raise TranslationError("translated text is empty")
                attempts.append(TranslationAttempt(provider_name, "success"))
                notice = ""
                if fallback_level == 1:
                    notice = "有道翻译当前不可用，已自动切换到 Google 翻译。"
                return TranslationCascadeResult(
                    source_text=request.source_text,
                    translated_text=result.translated_text,
                    source_language=result.source_language,
                    target_language=result.target_language,
                    provider=result.provider or provider_name,
                    model="",
                    request_id=request.request_id,
                    fallback_level=fallback_level,
                    notice=notice,
                    attempts=tuple(attempts),
                )
            except TextNormalizationError:
                raise
            except Exception:  # noqa: BLE001 - unavailable provider advances cascade
                attempts.append(TranslationAttempt(provider_name, "unavailable"))
            finally:
                self._close_provider(provider)

        try:
            ai_result = self._translate_ai(
                request,
                fallback_level=2,
                notice="有道和 Google 翻译当前不可用，已使用 AI 翻译。",
                terminology=normalized_terminology,
            )
        except Exception as exc:
            raise TranslationError("all translation providers are unavailable") from exc

        return TranslationCascadeResult(
            source_text=ai_result.source_text,
            translated_text=ai_result.translated_text,
            source_language=ai_result.source_language,
            target_language=ai_result.target_language,
            provider=ai_result.provider,
            model=ai_result.model,
            request_id=ai_result.request_id,
            fallback_level=ai_result.fallback_level,
            notice=ai_result.notice,
            attempts=tuple(attempts) + ai_result.attempts,
        )


__all__ = [
    "TranslationAttempt",
    "TranslationCascadeResult",
    "TranslationFallbackService",
    "TranslationProviderMode",
]
