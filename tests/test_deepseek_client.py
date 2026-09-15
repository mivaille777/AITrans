from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.client import DeepSeekClient
from app.ai.errors import AIConfigurationError, AIResponseError
from app.ai.secrets import get_deepseek_api_key


class FakeCompletions:
    def __init__(self, *, content: object = "OK", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeSDKClient:
    def __init__(self, completions: FakeCompletions | None = None) -> None:
        self.completions = completions or FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_default_request_uses_flash_and_disables_thinking() -> None:
    sdk = FakeSDKClient()
    client = DeepSeekClient(sdk_client=sdk)

    result = client.complete(
        system_prompt="Translate faithfully.",
        user_prompt="Hello",
    )

    assert result == "OK"
    request = sdk.completions.calls[0]
    assert request["model"] == "deepseek-v4-flash"
    assert request["stream"] is False
    assert request["temperature"] == 0.2
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_thinking_mode_omits_temperature() -> None:
    sdk = FakeSDKClient()
    client = DeepSeekClient(sdk_client=sdk, thinking_enabled=True)

    client.complete(
        system_prompt="Think carefully.",
        user_prompt="Question",
        temperature=1.9,
    )

    request = sdk.completions.calls[0]
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "temperature" not in request


def test_rejects_unsupported_model() -> None:
    with pytest.raises(AIConfigurationError):
        DeepSeekClient(model="deepseek-chat", sdk_client=FakeSDKClient())


def test_rejects_invalid_temperature_before_request() -> None:
    sdk = FakeSDKClient()
    client = DeepSeekClient(sdk_client=sdk)

    with pytest.raises(AIConfigurationError):
        client.complete(
            system_prompt="System",
            user_prompt="User",
            temperature=2.1,
        )

    assert sdk.completions.calls == []


def test_empty_response_is_rejected() -> None:
    client = DeepSeekClient(sdk_client=FakeSDKClient(FakeCompletions(content="  ")))

    with pytest.raises(AIResponseError):
        client.complete(system_prompt="System", user_prompt="User")


def test_unknown_sdk_failure_is_sanitized() -> None:
    sdk = FakeSDKClient(FakeCompletions(error=RuntimeError("secret detail")))
    client = DeepSeekClient(sdk_client=sdk)

    with pytest.raises(AIResponseError, match="DeepSeek API request failed"):
        client.complete(system_prompt="System", user_prompt="User")


def test_injected_sdk_client_is_not_closed_by_wrapper() -> None:
    sdk = FakeSDKClient()
    client = DeepSeekClient(sdk_client=sdk)

    client.close()

    assert sdk.closed is False


class EmptyCredentialStore:
    def get(self, _provider: str) -> None:
        return None


def test_missing_api_key_is_configuration_error() -> None:
    with pytest.raises(AIConfigurationError):
        get_deepseek_api_key(credential_store=EmptyCredentialStore())
