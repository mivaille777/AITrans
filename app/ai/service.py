"""Application service for provider-independent AI text operations."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.ai.errors import AIConfigurationError, AIError, AIResponseError
from app.ai.models import AITextAction, AITextRequest, AITextResult
from app.ai.provider import AITextProvider, DeepSeekTextProvider

DEFAULT_AI_SOURCE_LANGUAGE = "auto"
DEFAULT_AI_TARGET_LANGUAGE = "zh-CN"
DEFAULT_AI_POLISH_STYLE = "general"


class AITextService:
    """Validate AI requests and orchestrate one text provider.

    The service is the application-facing boundary used by Qt workers and,
    later, the controller. Provider-specific SDK details stay below this
    layer. Request metadata is authoritative and is normalized onto returned
    results so a provider cannot accidentally corrupt request-version or task
    metadata used by the UI.
    """

    def __init__(self, provider: AITextProvider | Any | None = None) -> None:
        self.provider = provider if provider is not None else DeepSeekTextProvider()

    @property
    def provider_name(self) -> str:
        """Return a stable provider label for logs and UI metadata."""

        name = getattr(self.provider, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return type(self.provider).__name__

    @property
    def model(self) -> str:
        """Return the active model identifier when the provider exposes one."""

        value = getattr(self.provider, "model", "")
        return str(value).strip() or "unknown"

    @staticmethod
    def _validate_request(request: object) -> AITextRequest:
        if not isinstance(request, AITextRequest):
            raise AIConfigurationError("AI text service requires an AITextRequest.")
        if not isinstance(request.source_text, str) or not request.source_text.strip():
            raise AIConfigurationError("AI source text must not be empty.")
        if not isinstance(request.action, AITextAction):
            raise AIConfigurationError("Unsupported AI text action.")
        if (
            not isinstance(request.source_language, str)
            or not request.source_language.strip()
        ):
            raise AIConfigurationError("AI source language must not be empty.")
        if request.action is AITextAction.TRANSLATE and (
            not isinstance(request.target_language, str)
            or not request.target_language.strip()
        ):
            raise AIConfigurationError("AI target language must not be empty.")
        if not isinstance(request.style, str) or not request.style.strip():
            raise AIConfigurationError("AI text style must not be empty.")
        if isinstance(request.request_id, bool) or not isinstance(
            request.request_id, int
        ):
            raise AIConfigurationError("AI request_id must be an integer.")
        if (
            not isinstance(request.terminology, tuple)
            or len(request.terminology) > 32
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 1000
                for item in request.terminology
            )
        ):
            raise AIConfigurationError("AI terminology preferences are invalid.")
        return request

    def execute(self, request: AITextRequest) -> AITextResult:
        """Execute one structured AI request through the configured provider."""

        validated = self._validate_request(request)
        try:
            result = self.provider.execute(validated)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize provider failures
            error = AIResponseError("AI text provider failed.")
            error.__cause__ = exc
            raise error

        if not isinstance(result, AITextResult):
            raise AIResponseError("AI text provider returned an unsupported result.")
        if not isinstance(result.output_text, str) or not result.output_text.strip():
            raise AIResponseError("AI text provider returned empty content.")

        return replace(
            result,
            source_text=validated.source_text,
            output_text=result.output_text.strip(),
            action=validated.action,
            source_language=validated.source_language,
            target_language=validated.target_language,
            style=validated.style,
            request_id=validated.request_id,
        )

    def translate(
        self,
        source_text: str,
        *,
        source_language: str = DEFAULT_AI_SOURCE_LANGUAGE,
        target_language: str = DEFAULT_AI_TARGET_LANGUAGE,
        request_id: int = 0,
        terminology: tuple[str, ...] = (),
    ) -> AITextResult:
        """Convenience entry point for AI translation."""

        return self.execute(
            AITextRequest(
                source_text=source_text,
                action=AITextAction.TRANSLATE,
                source_language=source_language,
                target_language=target_language,
                style=DEFAULT_AI_POLISH_STYLE,
                request_id=request_id,
                terminology=tuple(
                    str(item).strip()[:1000]
                    for item in terminology[:32]
                    if str(item).strip()
                ),
            )
        )

    def polish(
        self,
        source_text: str,
        *,
        source_language: str = DEFAULT_AI_SOURCE_LANGUAGE,
        style: str = DEFAULT_AI_POLISH_STYLE,
        request_id: int = 0,
    ) -> AITextResult:
        """Convenience entry point for same-language AI polishing."""

        normalized_source_language = (
            str(source_language).strip() or DEFAULT_AI_SOURCE_LANGUAGE
        )
        return self.execute(
            AITextRequest(
                source_text=source_text,
                action=AITextAction.POLISH,
                source_language=normalized_source_language,
                # Polishing is same-language generation. Keep the result
                # metadata truthful instead of inheriting the translation
                # service's Chinese default target.
                target_language=normalized_source_language,
                style=style,
                request_id=request_id,
            )
        )

    def close(self) -> None:
        """Release resources owned by the configured provider."""

        close = getattr(self.provider, "close", None)
        if callable(close):
            close()


__all__ = [
    "DEFAULT_AI_POLISH_STYLE",
    "DEFAULT_AI_SOURCE_LANGUAGE",
    "DEFAULT_AI_TARGET_LANGUAGE",
    "AITextService",
]
