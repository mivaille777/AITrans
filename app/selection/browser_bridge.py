"""Loopback bridge for zero-keyboard browser selection capture.

The browser extension posts structured selection snapshots to a local HTTP
endpoint bound only to 127.0.0.1. Automatic translation can then consume the
fresh snapshot before falling back to Windows UI Automation. This module does
not read or write the clipboard and never synthesizes keyboard input.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock, Thread
from time import monotonic
from typing import Any, Callable

from app.models.selection import SelectedText, SelectionContext
from app.selection.errors import SelectionError

LOGGER_NAME = "desktop_translator"
DEFAULT_BROWSER_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BROWSER_BRIDGE_PORT = 8765
BROWSER_SELECTION_PATH = "/v1/selection"
BRIDGE_HEADER_NAME = "X-AITrans-Bridge"
BRIDGE_HEADER_VALUE = "selection-v1"
MAX_BROWSER_BRIDGE_PAYLOAD_BYTES = 64 * 1024
DEFAULT_BROWSER_SELECTION_MAX_AGE_SECONDS = 1.25
GESTURE_SNAPSHOT_GRACE_SECONDS = 0.35

BROWSER_PROCESS_NAMES = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "msedgewebview2.exe",
        "brave.exe",
        "firefox.exe",
        "opera.exe",
        "vivaldi.exe",
    }
)


def _bounded_text(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) > limit:
        return text[:limit]
    return text


def _normalized_process_name(value: object) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()


@dataclass(frozen=True, slots=True)
class BrowserSelectionSnapshot:
    """One structured browser selection received from the extension."""

    text: str
    url: str = ""
    title: str = ""
    heading: str = ""
    context_before: str = ""
    context_after: str = ""
    frame_url: str = ""
    top_level: bool = True
    browser_captured_at_ms: float | None = None
    received_at: float = 0.0

    @property
    def nearby_context(self) -> str:
        parts = [self.context_before, self.text, self.context_after]
        return " ".join(part for part in parts if part).strip()


@dataclass(frozen=True, slots=True)
class BrowserBridgeStatus:
    """Privacy-bounded diagnostics suitable for a user-facing settings page."""

    running: bool
    host: str
    port: int
    has_extension_activity: bool
    last_activity_age_seconds: float | None = None
    last_title: str = ""
    last_url: str = ""
    last_heading: str = ""

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"


class _BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, bridge: "BrowserSelectionBridge"):
        self.bridge = bridge
        super().__init__(server_address, handler_class)


class _BrowserBridgeRequestHandler(BaseHTTPRequestHandler):
    server: _BridgeHTTPServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Keep the desktop log free from raw browser URLs/selection contents.
        return

    def _write_status(self, status: int, body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)
        # Flush the complete response while the handler still owns the socket.
        # This matters on Windows where an early request rejection can otherwise
        # surface to urllib as WinError 10053 instead of the intended HTTPError.
        self.wfile.flush()

    def _read_bounded_body(self) -> tuple[int, bytes | None]:
        """Read one bounded POST body before protocol-level rejection.

        Consuming a small, declared request body before returning a 4xx avoids
        Windows resetting the TCP connection because unread inbound bytes remain
        when BaseHTTPRequestHandler finishes the request. The bytes are not
        parsed or trusted until bridge header/origin validation succeeds.
        """

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return 400, None
        if length <= 0:
            return 400, None
        if length > MAX_BROWSER_BRIDGE_PAYLOAD_BYTES:
            return 413, None
        try:
            raw = self.rfile.read(length)
        except OSError:
            return 400, None
        if len(raw) != length:
            return 400, None
        return 200, raw

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler contract
        # A normal webpage attempting the custom bridge header would need a
        # successful CORS preflight. Refuse it; the extension service worker
        # has explicit localhost host permission and does not need page CORS.
        self._write_status(403)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path != "/v1/status":
            self._write_status(404)
            return
        body = json.dumps(
            {"ok": True, "bridge": "selection-v1"},
            separators=(",", ":"),
        ).encode("utf-8")
        self._write_status(200, body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path != BROWSER_SELECTION_PATH:
            self._write_status(404)
            return

        body_status, raw = self._read_bounded_body()
        if raw is None:
            self._write_status(body_status)
            return

        # Authentication still happens before payload decoding/validation. We
        # only consumed the bounded raw bytes above so Windows can receive a
        # deterministic HTTP response instead of a connection reset.
        if self.headers.get(BRIDGE_HEADER_NAME, "") != BRIDGE_HEADER_VALUE:
            self._write_status(403)
            return

        origin = self.headers.get("Origin", "").strip().casefold()
        if origin and not (
            origin.startswith("chrome-extension://")
            or origin.startswith("moz-extension://")
            or origin.startswith("extension://")
        ):
            self._write_status(403)
            return

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_status(400)
            return
        if not isinstance(payload, dict):
            self._write_status(400)
            return

        try:
            self.server.bridge.ingest_payload(payload)
        except SelectionError:
            self._write_status(422)
            return
        except Exception:
            self._write_status(500)
            return
        self._write_status(204)


class BrowserSelectionBridge:
    """Receive and serve fresh browser selections from the companion extension."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_BROWSER_BRIDGE_HOST,
        port: int = DEFAULT_BROWSER_BRIDGE_PORT,
        max_age_seconds: float = DEFAULT_BROWSER_SELECTION_MAX_AGE_SECONDS,
        clock: Callable[[], float] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.host = str(host or DEFAULT_BROWSER_BRIDGE_HOST)
        self.port = int(port)
        try:
            max_age = float(max_age_seconds)
            if not math.isfinite(max_age):
                raise ValueError("max age must be finite")
        except (TypeError, ValueError):
            max_age = DEFAULT_BROWSER_SELECTION_MAX_AGE_SECONDS
        self.max_age_seconds = max(0.05, max_age)
        self._clock = clock or monotonic
        self.logger = logger or logging.getLogger(LOGGER_NAME)
        self._lock = RLock()
        self._latest: BrowserSelectionSnapshot | None = None
        self._server: _BridgeHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._server is not None

    @property
    def bound_port(self) -> int:
        with self._lock:
            server = self._server
            if server is None:
                return self.port
            return int(server.server_address[1])

    def status_snapshot(self) -> BrowserBridgeStatus:
        """Return safe runtime diagnostics without exposing selected text."""

        with self._lock:
            server = self._server
            snapshot = self._latest
            running = server is not None
            port = int(server.server_address[1]) if server is not None else self.port
        age: float | None = None
        if snapshot is not None:
            try:
                age = max(0.0, float(self._clock()) - float(snapshot.received_at))
            except (TypeError, ValueError):
                age = None
        return BrowserBridgeStatus(
            running=running,
            host=self.host,
            port=port,
            has_extension_activity=snapshot is not None,
            last_activity_age_seconds=age,
            last_title=snapshot.title if snapshot is not None else "",
            last_url=snapshot.url if snapshot is not None else "",
            last_heading=snapshot.heading if snapshot is not None else "",
        )

    def start(self) -> bool:
        """Start the loopback receiver once without blocking the Qt thread."""

        with self._lock:
            if self._server is not None:
                return True
            try:
                server = _BridgeHTTPServer(
                    (self.host, self.port),
                    _BrowserBridgeRequestHandler,
                    self,
                )
            except OSError as exc:
                self.logger.warning(
                    "browser_selection_bridge_start_failed error_type=%s",
                    type(exc).__name__,
                )
                return False
            thread = Thread(
                target=server.serve_forever,
                name="browser-selection-bridge",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            thread.start()
        self.logger.info(
            "browser_selection_bridge_started host=%s port=%s",
            self.host,
            self.bound_port,
        )
        return True

    def stop(self) -> None:
        """Stop the receiver and release the loopback port."""

        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        finally:
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(0.75)
        self.logger.info("browser_selection_bridge_stopped")

    def ingest_payload(
        self,
        payload: dict[str, Any],
        *,
        received_at: float | None = None,
    ) -> BrowserSelectionSnapshot:
        """Validate and remember one bounded extension payload."""

        try:
            version = int(payload.get("version", 1))
        except (TypeError, ValueError):
            raise SelectionError("browser selection protocol is invalid")
        if version != 1:
            raise SelectionError("browser selection protocol is unsupported")
        if str(payload.get("type", "selection")).casefold() != "selection":
            raise SelectionError("browser selection payload is unsupported")

        text = _bounded_text(payload.get("text"), 20_000)
        if not text:
            raise SelectionError("browser selection is empty")

        captured_at_ms: float | None = None
        raw_captured_at = payload.get("captured_at_ms")
        if raw_captured_at is not None:
            try:
                candidate = float(raw_captured_at)
                if math.isfinite(candidate) and candidate >= 0:
                    captured_at_ms = candidate
            except (TypeError, ValueError):
                captured_at_ms = None

        snapshot = BrowserSelectionSnapshot(
            text=text,
            url=_bounded_text(payload.get("url"), 4096),
            title=_bounded_text(payload.get("title"), 1024),
            heading=_bounded_text(payload.get("heading"), 1024),
            context_before=_bounded_text(payload.get("context_before"), 1500),
            context_after=_bounded_text(payload.get("context_after"), 1500),
            frame_url=_bounded_text(payload.get("frame_url"), 4096),
            top_level=bool(payload.get("top_level", True)),
            browser_captured_at_ms=captured_at_ms,
            received_at=self._clock() if received_at is None else float(received_at),
        )
        with self._lock:
            self._latest = snapshot
        self.logger.debug(
            "browser_selection_received text_length=%s has_url=%s has_context=%s",
            len(snapshot.text),
            bool(snapshot.url),
            bool(snapshot.context_before or snapshot.context_after),
        )
        return snapshot

    def latest_snapshot(
        self,
        *,
        context: SelectionContext | None = None,
        max_age_seconds: float | None = None,
    ) -> BrowserSelectionSnapshot:
        """Return a fresh snapshot matching the current browser gesture."""

        if context is not None and context.process_name:
            process_name = _normalized_process_name(context.process_name)
            if process_name not in BROWSER_PROCESS_NAMES:
                raise SelectionError("foreground process is not a supported browser")

        with self._lock:
            snapshot = self._latest
        if snapshot is None:
            raise SelectionError("browser selection bridge has no snapshot")

        limit = self.max_age_seconds if max_age_seconds is None else float(max_age_seconds)
        now = self._clock()
        if now - snapshot.received_at > max(0.0, limit):
            raise SelectionError("browser selection bridge snapshot is stale")

        if context is not None and context.captured_at is not None:
            if snapshot.received_at < (
                float(context.captured_at) - GESTURE_SNAPSHOT_GRACE_SECONDS
            ):
                raise SelectionError("browser selection predates current gesture")

        return snapshot

    def get_selected_text_with_context(
        self,
        context: SelectionContext | None,
    ) -> SelectedText:
        """Expose the fresh extension snapshot as a SelectionProvider-like result."""

        snapshot = self.latest_snapshot(context=context)
        return SelectedText(snapshot.text, provider="browser_bridge")

    def get_selected_text(self) -> SelectedText:
        return self.get_selected_text_with_context(None)


__all__ = [
    "BROWSER_PROCESS_NAMES",
    "BROWSER_SELECTION_PATH",
    "BRIDGE_HEADER_NAME",
    "BRIDGE_HEADER_VALUE",
    "BrowserBridgeStatus",
    "BrowserSelectionBridge",
    "BrowserSelectionSnapshot",
    "DEFAULT_BROWSER_BRIDGE_HOST",
    "DEFAULT_BROWSER_BRIDGE_PORT",
    "DEFAULT_BROWSER_SELECTION_MAX_AGE_SECONDS",
]
