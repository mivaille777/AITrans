"""Generic OpenAI-compatible client/provider used by configurable AI backends."""

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
from app.ai.provider import DeepSeekTextProvider
from app.ai.runtime_status import track_llm_request
from app.ai.secrets import ProviderCredentialStore, get_provider_api_key

DEFAULT_COMPATIBLE_TIMEOUT_SECONDS = 15.0
DEFAULT_COMPATIBLE_MAX_RETRIES = 1


class OpenAICompatibleClient:
    """Call an arbitrary Chat-Completions-compatible provider."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_COMPATIBLE_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_COMPATIBLE_MAX_RETRIES,
        sdk_client: Any | None = None,
        credential_store: ProviderCredentialStore | Any | None = None,
    ) -> None:
        self.base_url = self._validate_base_url(base_url)
        self.model = self._validate_model(model)
        self.timeout = self._validate_timeout(timeout)
        self.max_retries = self._validate_retries(max_retries)
        self._owns_sdk_client = sdk_client is None

        if sdk_client is not None:
            self._client = sdk_client
        else:
            resolved_api_key = get_provider_api_key(
                "openai_compatible",
                credential_store=credential_store,
            )
            self._client = OpenAI(
                api_key=resolved_api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )

    @staticmethod
    def _validate_base_url(value: object) -> str:
        candidate = str(value).strip().rstrip("/")
        if not candidate.startswith(("https://", "http://")):
            raise AIConfigurationError(
                "OpenAI-compatible base URL must start with http:// or https://."
            )
        return candidate

    @staticmethod
    def _validate_model(value: object) -> str:
        candidate = str(value).strip()
        if not candidate:
            raise AIConfigurationError(
                "OpenAI-compatible provider requires a model identifier."
            )
        return candidate

    @staticmethod
    def _validate_timeout(value: object) -> float:
        try:
            timeout = float(value)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError(
                "OpenAI-compatible timeout must be a positive number."
            ) from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise AIConfigurationError(
                "OpenAI-compatible timeout must be a positive number."
            )
        return timeout

    @staticmethod
    def _validate_retries(value: object) -> int:
        if isinstance(value, bool):
            raise AIConfigurationError(
                "OpenAI-compatible max_retries must be a nonnegative integer."
            )
        try:
            retries = int(value)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError(
                "OpenAI-compatible max_retries must be a nonnegative integer."
            ) from exc
        if retries < 0 or retries != value:
            raise AIConfigurationError(
                "OpenAI-compatible max_retries must be a nonnegative integer."
            )
        return retries

    @staticmethod
    def _validate_temperature(value: object) -> float:
        try:
            temperature = float(value)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError(
                "OpenAI-compatible temperature must be between 0 and 2."
            ) from exc
        if not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
            raise AIConfigurationError(
                "OpenAI-compatible temperature must be between 0 and 2."
            )
        return temperature

    @staticmethod
    def _validate_max_tokens(value: object | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise AIConfigurationError(
                "OpenAI-compatible max_tokens must be a positive integer."
            )
        try:
            max_tokens = int(value)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError(
                "OpenAI-compatible max_tokens must be a positive integer."
            ) from exc
        if max_tokens <= 0 or max_tokens != value:
            raise AIConfigurationError(
                "OpenAI-compatible max_tokens must be a positive integer."
            )
        return max_tokens

    def _complete_request(self, request: dict[str, Any]) -> str:
        route_key = f"openai_compatible|{self.model}|{self.base_url}"
        with track_llm_request(
            provider="openai_compatible",
            model=self.model,
            route_key=route_key,
        ):
            return self._complete_request_untracked(request)

    def _complete_request_untracked(self, request: dict[str, Any]) -> str:
        try:
            response = self._client.chat.completions.create(**request)
        except AuthenticationError as exc:
            raise AIAuthenticationError(
                "OpenAI-compatible API authentication failed."
            ) from exc
        except RateLimitError as exc:
            raise AIRateLimitError(
                "OpenAI-compatible API rate limit exceeded."
            ) from exc
        except APITimeoutError as exc:
            raise AITimeoutError(
                "OpenAI-compatible API request timed out."
            ) from exc
        except APIConnectionError as exc:
            raise AIConnectionError(
                "Unable to connect to the OpenAI-compatible API."
            ) from exc
        except APIStatusError as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                raise AIResponseError(
                    "OpenAI-compatible API request failed."
                ) from exc
            raise AIResponseError(
                f"OpenAI-compatible API request failed with HTTP status {status_code}."
            ) from exc
        except AIError:
            raise
        except Exception as exc:
            raise AIResponseError(
                "OpenAI-compatible API request failed."
            ) from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise AIResponseError(
                "OpenAI-compatible API returned an invalid response."
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise AIResponseError(
                "OpenAI-compatible API returned empty content."
            )
        return content.strip()

    def probe(self) -> None:
        try:
            self._client.models.list()
        except AuthenticationError as exc:
            raise AIAuthenticationError(
                "OpenAI-compatible API authentication failed."
            ) from exc
        except RateLimitError as exc:
            raise AIRateLimitError(
                "OpenAI-compatible API rate limit exceeded."
            ) from exc
        except APITimeoutError as exc:
            raise AITimeoutError(
                "OpenAI-compatible API request timed out."
            ) from exc
        except APIConnectionError as exc:
            raise AIConnectionError(
                "Unable to connect to the OpenAI-compatible API."
            ) from exc
        except APIStatusError as exc:
            status_code = getattr(exc, "status_code", None)
            detail = f" with HTTP status {status_code}" if status_code is not None else ""
            raise AIResponseError(
                f"OpenAI-compatible API health check failed{detail}."
            ) from exc
        except Exception as exc:
            raise AIResponseError(
                "OpenAI-compatible API health check failed."
            ) from exc

    def complete_messages(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Complete provider-neutral chat messages, including multimodal content."""

        if not isinstance(messages, list) or not messages:
            raise AIConfigurationError("Messages must be a non-empty list.")
        if not all(isinstance(message, dict) for message in messages):
            raise AIConfigurationError("Each message must be a mapping.")

        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": self._validate_temperature(temperature),
        }
        validated_max_tokens = self._validate_max_tokens(max_tokens)
        if validated_max_tokens is not None:
            request["max_tokens"] = validated_max_tokens
        return self._complete_request(request)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise AIConfigurationError("System prompt must not be empty.")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise AIConfigurationError("User prompt must not be empty.")

        return self.complete_messages(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def close(self) -> None:
        if not self._owns_sdk_client:
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


class OpenAICompatibleTextProvider(DeepSeekTextProvider):
    """Reuse the hardened translation/polish pipeline with a custom backend."""

    name = "openai_compatible"


__all__ = [
    "DEFAULT_COMPATIBLE_MAX_RETRIES",
    "DEFAULT_COMPATIBLE_TIMEOUT_SECONDS",
    "OpenAICompatibleClient",
    "OpenAICompatibleTextProvider",
]
