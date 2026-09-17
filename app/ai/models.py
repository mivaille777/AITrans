"""Provider-independent models for AI text operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AITextAction(str, Enum):
    """Supported AI text operations."""

    TRANSLATE = "translate"
    POLISH = "polish"


@dataclass(frozen=True, slots=True)
class AITextRequest:
    """One provider-independent AI text request."""

    source_text: str
    action: AITextAction
    source_language: str = "auto"
    target_language: str = "zh-CN"
    style: str = "general"
    request_id: int = 0
    terminology: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AITextResult:
    """Provider-independent output returned by an AI text provider."""

    source_text: str
    output_text: str
    action: AITextAction
    provider: str
    model: str
    source_language: str = "auto"
    target_language: str = "zh-CN"
    style: str = "general"
    request_id: int = 0

    @property
    def text(self) -> str:
        """Short alias for callers that only need the generated text."""

        return self.output_text


__all__ = [
    "AITextAction",
    "AITextRequest",
    "AITextResult",
]
