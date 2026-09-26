"""Explicit container environment construction and trace-value redaction."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from ipaddress import ip_address

_SAFE_SANDBOX_ENVIRONMENT = {
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "MPLBACKEND": "Agg",
    "PATH": "/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "TEMP": "/tmp",
    "TMP": "/tmp",
    "TMPDIR": "/tmp",
}
_SECRET_SUFFIXES = ("_TOKEN", "_SECRET", "_PASSWORD", "_KEY")
_SECRET_PREFIXES = ("AWS_", "AZURE_", "GOOGLE_")
_SECRET_EXACT_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "SSH_AUTH_SOCK",
    }
)
_MIN_SECRET_VALUE_LENGTH = 4


def build_sandbox_environment(*, proxy_address: str | None = None) -> dict[str, str]:
    """Return only fixed safe values and, when requested, the controlled proxy."""

    environment = dict(_SAFE_SANDBOX_ENVIRONMENT)
    if proxy_address is None:
        return environment

    try:
        address = ip_address(str(proxy_address).strip())
    except ValueError as exc:
        raise ValueError("The sandbox proxy address must be an IPv4 address.") from exc
    if (
        address.version != 4
        or not address.is_private
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
    ):
        raise ValueError("The sandbox proxy address must be an IPv4 bridge address.")

    endpoint = f"http://{address}:8888"
    environment.update(
        {
            "ALL_PROXY": "",
            "HTTPS_PROXY": endpoint,
            "HTTP_PROXY": endpoint,
            "NO_PROXY": "",
            "all_proxy": "",
            "https_proxy": endpoint,
            "http_proxy": endpoint,
            "no_proxy": "",
        }
    )
    return environment


def is_sensitive_environment_name(name: str) -> bool:
    """Return whether an environment variable name should be treated as secret."""

    normalized = str(name or "").strip().upper()
    return (
        normalized in _SECRET_EXACT_NAMES
        or normalized.endswith(_SECRET_SUFFIXES)
        or normalized.startswith(_SECRET_PREFIXES)
    )


def known_secret_environment_values(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Read sensitive host values for output scrubbing; never pass them to Docker."""

    source = os.environ if environment is None else environment
    values = {
        str(value)
        for name, value in source.items()
        if is_sensitive_environment_name(name)
        and value
        and len(str(value)) >= _MIN_SECRET_VALUE_LENGTH
    }
    return tuple(sorted(values, key=lambda value: (-len(value), value)))


def redact_known_secret_values(
    text: str,
    *,
    secret_values: Iterable[str] | None = None,
) -> str:
    """Remove known host secret values from text before it enters Sandbox Trace."""

    result = str(text or "")
    values = (
        known_secret_environment_values()
        if secret_values is None
        else tuple(secret_values)
    )
    for value in sorted(
        {
            str(item)
            for item in values
            if item and len(str(item)) >= _MIN_SECRET_VALUE_LENGTH
        },
        key=lambda item: (-len(item), item),
    ):
        result = result.replace(value, "[REDACTED]")
    return result


__all__ = [
    "build_sandbox_environment",
    "is_sensitive_environment_name",
    "known_secret_environment_values",
    "redact_known_secret_values",
]
