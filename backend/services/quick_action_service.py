from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.ai.chat.models import ChatContext, ChatRequest, ReadingContext
from app.ai.chat.service import AIChatService
from app.ai.errors import AIConfigurationError
from app.ai.service import AITextService
from app.models.reading_actions import (
    READING_ANALYZE_EQUATION,
    READING_CONTEXT_TRANSLATE,
    READING_DEFINE_TERMS,
    READING_EXPLAIN,
    READING_SECTION_ROLE,
    READING_SECTION_SUMMARIZE,
    READING_SUMMARIZE,
    reading_action_prompt,
)

AI_POLISH = "ai_polish"
SUPPORTED_QUICK_ACTIONS = frozenset(
    {
        AI_POLISH,
        READING_CONTEXT_TRANSLATE,
        READING_EXPLAIN,
        READING_SUMMARIZE,
        READING_SECTION_ROLE,
        READING_DEFINE_TERMS,
        READING_ANALYZE_EQUATION,
        READING_SECTION_SUMMARIZE,
    }
)


@dataclass(frozen=True, slots=True)
class QuickActionResult:
    action: str
    output_text: str
    provider: str
    model: str
    request_id: int = 0


class QuickActionService:
    """Application boundary for source-bound AI actions."""

    def __init__(
        self,
        *,
        text_service: AITextService | Any | None = None,
        chat_service: AIChatService | Any | None = None,
    ) -> None:
        self._text_service = text_service
        self._chat_service = chat_service

    def _ensure_text_service(self) -> AITextService | Any:
        if self._text_service is None:
            self._text_service = AITextService()
        return self._text_service

    def _ensure_chat_service(self) -> AIChatService | Any:
        if self._chat_service is None:
            self._chat_service = AIChatService(self._ensure_text_service())
        return self._chat_service

    def status(self) -> tuple[bool, str, str, str]:
        try:
            service = self._ensure_text_service()
            return True, service.provider_name, service.model, ""
        except AIConfigurationError as exc:
            return False, "deepseek", "", str(exc)

    @staticmethod
    def _context(
        *,
        source_text: str,
        translated_text: str,
        resource_url: str,
        resource_title: str,
        section_heading: str,
        context_before: str,
        context_after: str,
        source_kind: str,
    ) -> ChatContext:
        return ChatContext(
            source_text=source_text,
            translated_text=translated_text,
            reading=ReadingContext(
                resource_url=resource_url,
                resource_title=resource_title,
                section_heading=section_heading,
                context_before=context_before,
                context_after=context_after,
                source_kind=source_kind,
            ),
        )

    def run(
        self,
        *,
        action: str,
        source_text: str,
        translated_text: str = "",
        source_language: str = "auto",
        target_language: str = "zh-CN",
        style: str = "academic",
        resource_url: str = "",
        resource_title: str = "",
        section_heading: str = "",
        context_before: str = "",
        context_after: str = "",
        source_kind: str = "browser_selection",
        request_id: int = 0,
    ) -> QuickActionResult:
        normalized_action = str(action).strip()
        if normalized_action not in SUPPORTED_QUICK_ACTIONS:
            raise AIConfigurationError(f"Unsupported quick action: {normalized_action or '<empty>'}.")

        if normalized_action == AI_POLISH:
            result = self._ensure_text_service().polish(
                source_text,
                source_language=source_language,
                style=style,
                request_id=request_id,
            )
            return QuickActionResult(
                action=normalized_action,
                output_text=result.output_text,
                provider=result.provider,
                model=result.model,
                request_id=result.request_id,
            )

        prompt = reading_action_prompt(
            normalized_action,
            target_language=target_language,
        )
        if not prompt:
            raise AIConfigurationError(f"No prompt registered for quick action: {normalized_action}.")

        context = self._context(
            source_text=source_text,
            translated_text=translated_text,
            resource_url=resource_url,
            resource_title=resource_title,
            section_heading=section_heading,
            context_before=context_before,
            context_after=context_after,
            source_kind=source_kind,
        )
        result = self._ensure_chat_service().execute(
            ChatRequest(
                session_id=f"quick-action-{uuid4().hex}",
                user_message=prompt,
                context=context,
                request_id=request_id,
            )
        )
        return QuickActionResult(
            action=normalized_action,
            output_text=result.output_text,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
        )

    def close(self) -> None:
        text_service = self._text_service
        chat_service = self._chat_service
        self._chat_service = None
        self._text_service = None

        chat_text_service = getattr(chat_service, "text_service", None)
        if chat_text_service is not None and chat_text_service is not text_service:
            close = getattr(chat_text_service, "close", None)
            if callable(close):
                close()
        if text_service is not None:
            text_service.close()
