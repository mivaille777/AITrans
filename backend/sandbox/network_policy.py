"""Exact-host egress policy and public-address validation for sandbox traffic."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NetworkPolicyError(ValueError):
    """A restricted sandbox network policy is invalid or unsafe."""


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["none", "restricted"] = "none"
    allowed_hosts: tuple[str, ...] = Field(default=(), max_length=64)

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            host = normalize_hostname(value)
            if host is None:
                raise ValueError("Network allowlist entries must be public hostnames.")
            normalized.append(host)
        if len(normalized) != len(set(normalized)):
            raise ValueError("Network allowlist contains duplicate hostnames.")
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_mode(self) -> NetworkPolicy:
        if self.mode == "none" and self.allowed_hosts:
            raise ValueError("A disabled network policy cannot include allowed hosts.")
        if self.mode == "restricted" and not self.allowed_hosts:
            raise ValueError(
                "Restricted network access requires at least one hostname."
            )
        return self


class NetworkPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["allow", "deny"]
    reason_code: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)
    host: str = ""
    addresses: tuple[str, ...] = ()


Resolver = Callable[..., list[tuple]]


def normalize_hostname(value: str) -> str | None:
    """Normalize an exact DNS hostname; reject IP literals and local suffixes."""

    raw = str(value or "").strip().rstrip(".")
    if not raw or len(raw) > 253 or any(char in raw for char in "/\\:@?#[]"):
        return None
    try:
        encoded = raw.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    try:
        ipaddress.ip_address(encoded)
    except ValueError:
        pass
    else:
        return None
    if encoded == "localhost" or encoded.endswith(
        (".localhost", ".local", ".internal")
    ):
        return None
    labels = encoded.split(".")
    if len(encoded) > 253 or any(not _valid_dns_label(label) for label in labels):
        return None
    return encoded


def _valid_dns_label(label: str) -> bool:
    return bool(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
    )


def resolve_public_addresses(
    host: str,
    *,
    resolver: Resolver | None = None,
) -> tuple[str, ...]:
    """Resolve once and fail closed if any returned address is not globally routed."""

    normalized = normalize_hostname(host)
    if normalized is None:
        raise NetworkPolicyError("The requested network host is invalid or local.")
    lookup = resolver or socket.getaddrinfo
    try:
        results = lookup(normalized, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise NetworkPolicyError(
            "The requested network host could not be resolved."
        ) from exc
    addresses: set[str] = set()
    for result in results:
        try:
            address = ipaddress.ip_address(str(result[4][0]).split("%", 1)[0])
        except (IndexError, TypeError, ValueError) as exc:
            raise NetworkPolicyError(
                "The requested network host resolved to an invalid address."
            ) from exc
        if not address.is_global:
            raise NetworkPolicyError(
                "The requested network host resolves to a non-public address."
            )
        addresses.add(str(address))
    if not addresses:
        raise NetworkPolicyError("The requested network host has no public addresses.")
    return tuple(sorted(addresses))


def evaluate_network_policy(
    target: str,
    policy: NetworkPolicy,
    *,
    resolver: Resolver | None = None,
) -> NetworkPolicyDecision:
    """Authorize one exact host and pin the public addresses checked by DNS."""

    host = normalize_hostname(target)
    if policy.mode != "restricted":
        return NetworkPolicyDecision(
            decision="deny",
            reason_code="network.disabled",
            reason="Sandbox network access is disabled.",
            host=host or "",
        )
    if host is None:
        return NetworkPolicyDecision(
            decision="deny",
            reason_code="network.host_invalid",
            reason="The requested network host is invalid or local.",
        )
    if host not in policy.allowed_hosts:
        return NetworkPolicyDecision(
            decision="deny",
            reason_code="network.host_not_allowlisted",
            reason="The requested host is not in the exact-host allowlist.",
            host=host,
        )
    try:
        addresses = resolve_public_addresses(host, resolver=resolver)
    except NetworkPolicyError as exc:
        return NetworkPolicyDecision(
            decision="deny",
            reason_code="network.destination_not_public",
            reason=str(exc),
            host=host,
        )
    return NetworkPolicyDecision(
        decision="allow",
        reason_code="network.host_allowed",
        reason="The exact hostname is allowlisted and resolves only to public addresses.",
        host=host,
        addresses=addresses,
    )


DEFAULT_NETWORK_POLICY = NetworkPolicy()


__all__ = [
    "DEFAULT_NETWORK_POLICY",
    "NetworkPolicy",
    "NetworkPolicyDecision",
    "NetworkPolicyError",
    "evaluate_network_policy",
    "normalize_hostname",
    "resolve_public_addresses",
]
