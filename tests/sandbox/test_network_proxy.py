from __future__ import annotations

import socket

from backend.sandbox.network_policy import NetworkPolicy
from backend.sandbox.network_proxy import (
    RestrictedEgressProxy,
    build_proxy_server_code,
)


def _resolver(address: str):
    return lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
    ]


def test_proxy_allows_exact_host_only_on_http_ports() -> None:
    proxy = RestrictedEgressProxy(
        NetworkPolicy(mode="restricted", allowed_hosts=("pypi.org",)),
        resolver=_resolver("1.1.1.1"),
    )

    assert proxy.authorize("pypi.org", 443).decision == "allow"
    assert proxy.authorize("pypi.org", 80).decision == "allow"
    assert proxy.authorize("github.com", 443).decision == "deny"
    assert proxy.authorize("pypi.org", 22).reason_code == "network.port_denied"


def test_proxy_rejects_private_dns_answers() -> None:
    proxy = RestrictedEgressProxy(
        NetworkPolicy(mode="restricted", allowed_hosts=("pypi.org",)),
        resolver=_resolver("10.0.0.5"),
    )

    decision = proxy.authorize("pypi.org", 443)

    assert decision.decision == "deny"
    assert decision.reason_code == "network.destination_not_public"


def test_proxy_sidecar_source_is_self_contained_and_compilable() -> None:
    source = build_proxy_server_code(
        NetworkPolicy(mode="restricted", allowed_hosts=("pypi.org",))
    )

    compile(source, "<sandbox-egress-proxy>", "exec")
    assert "ALLOWED_HOSTS = set(json.loads(" in source
    assert "pypi.org" in source
    assert "socket.create_connection((addresses[0], port)" in source
