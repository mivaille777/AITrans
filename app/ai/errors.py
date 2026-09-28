"""Provider-independent errors for AI text services."""

from __future__ import annotations


class AIError(RuntimeError):
    """Base error raised by the AI integration layer."""


class AIConfigurationError(AIError):
    """Raised when required AI configuration is missing or invalid."""


class AIAuthenticationError(AIError):
    """Raised when the remote AI service rejects authentication."""


class AIRateLimitError(AIError):
    """Raised when the remote AI service rate-limits the request."""


class AITimeoutError(AIError):
    """Raised when the remote AI request exceeds its timeout."""


class AIConnectionError(AIError):
    """Raised when the remote AI service cannot be reached."""


class AIResponseError(AIError):
    """Raised when the remote AI service returns an unusable response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


__all__ = [
    "AIAuthenticationError",
    "AIConfigurationError",
    "AIConnectionError",
    "AIError",
    "AIRateLimitError",
    "AIResponseError",
    "AITimeoutError",
]
