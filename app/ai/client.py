"""Reusable DeepSeek OpenAI-compatible client wrapper."""

from __future__ import annotations

import math
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIConnectionError,
    AIError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
)
from app.ai.runtime_status import track_llm_request
from app.ai.secrets import ProviderCredentialStore, get_deepseek_api_key

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
SUPPORTED_DEEPSEEK_MODELS = frozenset(
    {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    }
)
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_TEMPERATURE = 0.2


class DeepSeekClient:
    """Small application-facing wrapper around the DeepSeek Chat API.

    The wrapper keeps SDK details below the application boundary, defaults to
    the low-latency non-thinking mode used by translation/polish workflows,
    and converts SDK exceptions into stable application errors.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        thinking_enabled: bool = False,
        sdk_client: Any | None = None,
        credential_store: ProviderCredentialStore | Any | None = None,
    ) -> None:
        self.model = self._validate_model(model)
        self.base_url = DEEPSEEK_BASE_URL
        self.timeout = self._validate_timeout(timeout)
        self.max_retries = self._validate_retries(max_retries)
        self.thinking_enabled = bool(thinking_enabled)
        self._owns_sdk_client = sdk_client is None

        if sdk_client is not None:
            self._client = sdk_client
        else:
            resolved_api_key = get_deepseek_api_key(credential_store=credential_store)
            self._client = OpenAI(
                api_key=resolved_api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )

    @staticmethod
    def _validate_model(model: object) -> str:
        candidate = str(model).strip()
        if not candidate:
            raise AIConfigurationError("DeepSeek model must not be empty.")
        return candidate

    @staticmethod
    def _validate_timeout(timeout: object) -> float:
        try:
            value = float(timeout)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError("DeepSeek timeout must be a positive number.") from exc
        if not math.isfinite(value) or value <= 0:
            raise AIConfigurationError("DeepSeek timeout must be a positive number.")
        return value

    @staticmethod
    def _validate_retries(max_retries: object) -> int:
        if isinstance(max_retries, bool):
            raise AIConfigurationError("DeepSeek max_retries must be a nonnegative integer.")
        try:
            value = int(max_retries)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError(
                "DeepSeek max_retries must be a nonnegative integer."
            ) from exc
        if value < 0 or value != max_retries:
            raise AIConfigurationError(
                "DeepSeek max_retries must be a nonnegative integer."
            )
        return value

    @staticmethod
    def _validate_temperature(temperature: object) -> float:
        try:
            value = float(temperature)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError(
                "DeepSeek temperature must be between 0 and 2."
            ) from exc
        if not math.isfinite(value) or not 0.0 <= value <= 2.0:
            raise AIConfigurationError("DeepSeek temperature must be between 0 and 2.")
        return value

    @staticmethod
    def _validate_max_tokens(max_tokens: object | None) -> int | None:
        if max_tokens is None:
            return None
        if isinstance(max_tokens, bool):
            raise AIConfigurationError("DeepSeek max_tokens must be a positive integer.")
        try:
            value = int(max_tokens)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError("DeepSeek max_tokens must be a positive integer.") from exc
        if value <= 0 or value != max_tokens:
            raise AIConfigurationError("DeepSeek max_tokens must be a positive integer.")
        return value

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int | None = None,
    ) -> str:
        """Return one non-streaming chat completion as plain text."""

        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise AIConfigurationError("DeepSeek system_prompt must not be empty.")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise AIConfigurationError("DeepSeek user_prompt must not be empty.")

        validated_max_tokens = self._validate_max_tokens(max_tokens)
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "extra_body": {
                "thinking": {
                    "type": "enabled" if self.thinking_enabled else "disabled",
                }
            },
        }

        # DeepSeek documents temperature as ineffective in thinking mode. Omit
        # it there so callers cannot assume a value influenced the response.
        if not self.thinking_enabled:
            request["temperature"] = self._validate_temperature(temperature)
        if validated_max_tokens is not None:
            request["max_tokens"] = validated_max_tokens

        route_key = f"deepseek|{self.model}|{DEEPSEEK_BASE_URL}"
        with track_llm_request(
            provider="deepseek",
            model=self.model,
            route_key=route_key,
        ):
            return self._complete_request(request)

    def _complete_request(self, request: dict[str, Any]) -> str:
        try:
            response = self._client.chat.completions.create(**request)
        except AuthenticationError as exc:
            raise AIAuthenticationError("DeepSeek API authentication failed.") from exc
        except RateLimitError as exc:
            raise AIRateLimitError("DeepSeek API rate limit exceeded.") from exc
        except APITimeoutError as exc:
            raise AITimeoutError("DeepSeek API request timed out.") from exc
        except APIConnectionError as exc:
            raise AIConnectionError("Unable to connect to the DeepSeek API.") from exc
        except APIStatusError as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                raise AIResponseError("DeepSeek API request failed.") from exc
            raise AIResponseError(
                f"DeepSeek API request failed with HTTP status {status_code}."
            ) from exc
        except AIError:
            raise
        except Exception as exc:
            raise AIResponseError("DeepSeek API request failed.") from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise AIResponseError("DeepSeek API returned an invalid response.") from exc

        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("DeepSeek API returned empty content.")
        return content.strip()

    def close(self) -> None:
        """Release an SDK client created by this wrapper."""

        if not self._owns_sdk_client:
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TIMEOUT_SECONDS",
    "SUPPORTED_DEEPSEEK_MODELS",
    "DeepSeekClient",
]
