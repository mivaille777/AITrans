from __future__ import annotations

import pytest

from backend.sandbox.environment import (
    build_sandbox_environment,
    is_sensitive_environment_name,
    known_secret_environment_values,
    redact_known_secret_values,
)


def test_sandbox_environment_is_an_explicit_safe_allowlist(monkeypatch) -> None:
    sensitive_environment = {
        "AITRANS_TEST_SECRET": "test-secret-value",
        "GENERIC_TOKEN": "generic-token-value",
        "SERVICE_PASSWORD": "service-password-value",
        "SERVICE_KEY": "service-key-value",
        "OPENAI_API_KEY": "openai-key-value",
        "ANTHROPIC_API_KEY": "anthropic-key-value",
        "GITHUB_TOKEN": "github-token-value",
        "AWS_ACCESS_KEY_ID": "aws-access-key-value",
        "AWS_SECRET_ACCESS_KEY": "aws-secret-value",
        "AZURE_CLIENT_SECRET": "azure-secret-value",
        "GOOGLE_APPLICATION_CREDENTIALS": "google-credentials-path",
        "DATABASE_URL": "postgres://user:password@host/db",
        "SSH_AUTH_SOCK": "C:/Users/test/.ssh/agent.sock",
    }
    for name, value in sensitive_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HOME", "C:/Users/test")
    monkeypatch.setenv("PATH", "C:/Users/test/bin")

    environment = build_sandbox_environment()

    assert set(environment) == {
        "HOME",
        "LANG",
        "LC_ALL",
        "MPLBACKEND",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "TEMP",
        "TMP",
        "TMPDIR",
    }
    assert environment["HOME"] == "/tmp"
    assert environment["PATH"].startswith("/usr/local/bin:")
    assert not (set(environment) & set(sensitive_environment))
    assert not (set(environment.values()) & set(sensitive_environment.values()))


@pytest.mark.parametrize(
    "name",
    [
        "SERVICE_TOKEN",
        "SERVICE_SECRET",
        "SERVICE_PASSWORD",
        "SERVICE_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AZURE_CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ],
)
def test_sensitive_environment_patterns_are_recognized(name: str) -> None:
    assert is_sensitive_environment_name(name)


def test_restricted_network_adds_only_the_internal_proxy_settings() -> None:
    environment = build_sandbox_environment(proxy_address="172.30.0.2")

    endpoint = "http://172.30.0.2:8888"
    assert environment["HTTP_PROXY"] == endpoint
    assert environment["HTTPS_PROXY"] == endpoint
    assert environment["http_proxy"] == endpoint
    assert environment["https_proxy"] == endpoint
    assert environment["ALL_PROXY"] == ""
    assert environment["all_proxy"] == ""
    assert environment["NO_PROXY"] == ""
    assert environment["no_proxy"] == ""
    assert "OPENAI_API_KEY" not in environment


@pytest.mark.parametrize("address", ["", "127.0.0.1", "::1", "not-an-ip"])
def test_proxy_environment_rejects_invalid_or_local_address(address: str) -> None:
    with pytest.raises(ValueError):
        build_sandbox_environment(proxy_address=address)


def test_known_sensitive_values_are_redacted_from_trace_text() -> None:
    secret = "DO_NOT_LEAK_THIS"
    host_environment = {
        "AITRANS_TEST_SECRET": secret,
        "OPENAI_API_KEY": "another-known-key-value",
        "LANG": "C.UTF-8",
    }

    values = known_secret_environment_values(host_environment)
    redacted = redact_known_secret_values(
        f"stdout={secret}; key=another-known-key-value; lang=C.UTF-8",
        secret_values=values,
    )

    assert "DO_NOT_LEAK_THIS" not in redacted
    assert "another-known-key-value" not in redacted
    assert "C.UTF-8" in redacted
    assert redacted.count("[REDACTED]") == 2
