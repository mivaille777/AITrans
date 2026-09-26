from __future__ import annotations

import socket

import pytest
from pydantic import ValidationError

from backend.sandbox.network_policy import (
    NetworkPolicy,
    evaluate_network_policy,
    normalize_hostname,
    resolve_public_addresses,
)


def _resolver(address: str):
    return lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
    ]


def test_network_is_disabled_by_default() -> None:
    decision = evaluate_network_policy("example.com", NetworkPolicy())

    assert decision.decision == "deny"
    assert decision.reason_code == "network.disabled"


def test_restricted_policy_allows_only_exact_public_hostnames() -> None:
    policy = NetworkPolicy(mode="restricted", allowed_hosts=("pypi.org",))
    allowed = evaluate_network_policy(
        "PYPI.org.", policy, resolver=_resolver("1.1.1.1")
    )
    unknown = evaluate_network_policy(
        "files.pypi.org", policy, resolver=_resolver("1.1.1.1")
    )

    assert allowed.decision == "allow"
    assert allowed.host == "pypi.org"
    assert allowed.addresses == ("1.1.1.1",)
    assert unknown.decision == "deny"
    assert unknown.reason_code == "network.host_not_allowlisted"


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "service.localhost",
        "printer.local",
        "metadata.google.internal",
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "*.example.com",
    ],
)
def test_local_private_and_ip_targets_are_rejected(host: str) -> None:
    assert normalize_hostname(host) is None
    with pytest.raises(ValidationError):
        NetworkPolicy(mode="restricted", allowed_hosts=(host,))


def test_dns_answers_must_all_be_public() -> None:
    policy = NetworkPolicy(mode="restricted", allowed_hosts=("pypi.org",))

    decision = evaluate_network_policy(
        "pypi.org", policy, resolver=_resolver("169.254.169.254")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "network.destination_not_public"
    with pytest.raises(ValueError, match="non-public"):
        resolve_public_addresses("pypi.org", resolver=_resolver("127.0.0.1"))
