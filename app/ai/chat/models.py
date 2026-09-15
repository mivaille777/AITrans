"""Immutable data models for conversational AI requests and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True, slots=True)
class ReadingContext:
    """Bounded context describing what the user is currently reading.

    The model is intentionally source-neutral so browser, PDF and document
    providers can converge on the same prompt contract later.  It contains no
    credentials and no raw full-page/document payload.
    """

    resource_url: str = ""
    resource_title: str = ""
    section_heading: str = ""
    context_before: str = ""
    context_after: str = ""
    source_kind: str = ""

    @property
    def has_context(self) -> bool:
        return bool(
            self.resource_url
            or self.resource_title
            or self.section_heading
            or self.context_before
            or self.context_after
            or self.source_kind
        )


@dataclass(frozen=True, slots=True)
class ChatContext:
    source_text: str = ""
    translated_text: str = ""
    reading: ReadingContext = field(default_factory=ReadingContext)


@dataclass(frozen=True, slots=True)
class ChatRequest:
    session_id: str
    user_message: str
    context: ChatContext
    history: tuple[ChatMessage, ...] = ()
    request_id: int = 0
    tool_name: str = ""
    tool_context: str = ""
    knowledge_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatResult:
    session_id: str
    user_message: str
    output_text: str
    provider: str
    model: str
    request_id: int = 0


__all__ = [
    "ChatContext",
    "ChatMessage",
    "ChatRequest",
    "ChatResult",
    "ChatRole",
    "ReadingContext",
]
