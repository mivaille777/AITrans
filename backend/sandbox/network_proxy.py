"""Exact-host HTTP CONNECT proxy used by restricted sandbox egress."""

from __future__ import annotations

import json
from collections.abc import Callable

from backend.sandbox.network_policy import (
    NetworkPolicy,
    NetworkPolicyDecision,
    evaluate_network_policy,
    normalize_hostname,
)

_PROXY_SERVER_TEMPLATE = r"""from __future__ import annotations

import ipaddress
import json
import select
import socket
import socketserver
from urllib.parse import urlsplit

ALLOWED_HOSTS = set(json.loads(__ALLOWED_HOSTS_JSON__))
MAX_HEADER_BYTES = 65536
MAX_HEADER_COUNT = 100
CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 20

def public_addresses(host):
    values = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses = set()
    for value in values:
        address = ipaddress.ip_address(str(value[4][0]).split("%", 1)[0])
        if not address.is_global:
            raise ValueError("destination is not public")
        addresses.add(str(address))
    if not addresses:
        raise ValueError("destination has no public address")
    return sorted(addresses)

def read_request(sock):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ValueError("incomplete proxy request")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ValueError("proxy request headers are too large")
    marker = data.index(b"\r\n\r\n") + 4
    return bytes(data[:marker]), bytes(data[marker:])

def relay(left, right):
    peers = (left, right)
    while True:
        readable, _, _ = select.select(peers, (), (), IDLE_TIMEOUT)
        if not readable:
            return
        for source in readable:
            chunk = source.recv(65536)
            if not chunk:
                return
            target = right if source is left else left
            target.sendall(chunk)

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        try:
            self.request.settimeout(CONNECT_TIMEOUT)
            raw, buffered = read_request(self.request)
            lines = raw.decode("iso-8859-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            headers = [line for line in lines[1:] if line]
            if len(headers) > MAX_HEADER_COUNT:
                raise ValueError("too many request headers")
            for header in headers:
                if ":" not in header or any(ord(c) < 32 and c != "\\t" for c in header):
                    raise ValueError("invalid request header")

            if method.upper() == "CONNECT":
                parsed = urlsplit("//" + target)
                host = (parsed.hostname or "").rstrip(".").lower()
                port = parsed.port or 443
                if parsed.path or parsed.query or parsed.fragment or parsed.username:
                    raise ValueError("invalid CONNECT target")
                origin_request = b""
            else:
                parsed = urlsplit(target)
                host = (parsed.hostname or "").rstrip(".").lower()
                port = parsed.port or (80 if parsed.scheme.lower() == "http" else -1)
                if parsed.scheme.lower() != "http" or parsed.username or parsed.fragment:
                    raise ValueError("only HTTP proxy targets and HTTPS CONNECT are supported")
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                request_line = f"{method} {path} {version}\r\n"
                sanitized_headers = []
                for header in headers:
                    name, value = header.split(":", 1)
                    if name.strip().lower() in {
                        "proxy-authorization",
                        "proxy-connection",
                        "host",
                        "connection",
                        "keep-alive",
                    }:
                        continue
                    sanitized_headers.append(f"{name}: {value.strip()}\r\n")
                sanitized_headers.append(f"Host: {host}\r\n")
                sanitized_headers.append("Connection: close\r\n")
                origin_request = (request_line + "".join(sanitized_headers) + "\r\n").encode("iso-8859-1")

            if host not in ALLOWED_HOSTS or port not in {80, 443}:
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return
            addresses = public_addresses(host)
            upstream = socket.create_connection((addresses[0], port), timeout=CONNECT_TIMEOUT)
            upstream.settimeout(IDLE_TIMEOUT)
            self.request.settimeout(IDLE_TIMEOUT)
            if method.upper() == "CONNECT":
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                upstream.sendall(origin_request)
            if buffered:
                upstream.sendall(buffered)
            relay(self.request, upstream)
        except (OSError, ValueError, UnicodeError):
            try:
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
        finally:
            if upstream is not None:
                upstream.close()

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16

Server(("0.0.0.0", 8888), Handler).serve_forever()
"""


class RestrictedEgressProxy:
    """Policy wrapper used by the proxy service and by isolated tests."""

    def __init__(
        self,
        policy: NetworkPolicy,
        *,
        resolver: Callable[..., list[tuple]] | None = None,
    ) -> None:
        self.policy = policy
        self.resolver = resolver

    def authorize(self, host: str, port: int) -> NetworkPolicyDecision:
        normalized = normalize_hostname(host)
        if port not in {80, 443}:
            return NetworkPolicyDecision(
                decision="deny",
                reason_code="network.port_denied",
                reason="Only HTTP and HTTPS ports are available through the proxy.",
                host=normalized or "",
            )
        return evaluate_network_policy(
            normalized or host,
            self.policy,
            resolver=self.resolver,
        )


def build_proxy_server_code(policy: NetworkPolicy) -> str:
    if policy.mode != "restricted":
        raise ValueError("The restricted egress proxy requires a restricted policy.")
    allowlist_json = json.dumps(
        list(policy.allowed_hosts),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return _PROXY_SERVER_TEMPLATE.replace(
        "__ALLOWED_HOSTS_JSON__", repr(allowlist_json)
    )


__all__ = ["RestrictedEgressProxy", "build_proxy_server_code"]
