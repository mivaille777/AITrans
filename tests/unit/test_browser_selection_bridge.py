"""Regression tests for the Stage-3 browser Selection Bridge."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from app.models.selection import SelectedText, SelectionContext
from app.selection.browser_bridge import (
    BRIDGE_HEADER_NAME,
    BRIDGE_HEADER_VALUE,
    BrowserSelectionBridge,
)
from app.selection.errors import SelectionError


@dataclass
class FakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def _payload(text: str = "browser selected text") -> dict[str, object]:
    return {
        "version": 1,
        "type": "selection",
        "text": text,
        "url": "https://example.com/paper",
        "frame_url": "https://example.com/paper",
        "title": "Research Paper",
        "heading": "3. Method",
        "context_before": "before context",
        "context_after": "after context",
        "top_level": True,
        "captured_at_ms": 1234.5,
    }


def test_bridge_returns_fresh_browser_selection_with_reading_context() -> None:
    clock = FakeClock(20.0)
    bridge = BrowserSelectionBridge(clock=clock)
    snapshot = bridge.ingest_payload(_payload())

    selected = bridge.get_selected_text_with_context(
        SelectionContext(
            process_name="chrome.exe",
            captured_at=19.9,
        )
    )

    assert selected == SelectedText("browser selected text", provider="browser_bridge")
    assert snapshot.url == "https://example.com/paper"
    assert snapshot.title == "Research Paper"
    assert snapshot.heading == "3. Method"
    assert "before context" in snapshot.nearby_context
    assert "after context" in snapshot.nearby_context


def test_bridge_rejects_snapshot_for_non_browser_process() -> None:
    bridge = BrowserSelectionBridge(clock=FakeClock(10.0))
    bridge.ingest_payload(_payload())

    with pytest.raises(SelectionError, match="not a supported browser"):
        bridge.get_selected_text_with_context(
            SelectionContext(process_name="notepad.exe", captured_at=10.0)
        )


def test_bridge_rejects_stale_or_previous_gesture_snapshot() -> None:
    clock = FakeClock(30.0)
    bridge = BrowserSelectionBridge(clock=clock, max_age_seconds=1.0)
    bridge.ingest_payload(_payload(), received_at=30.0)

    clock.value = 31.1
    with pytest.raises(SelectionError, match="stale"):
        bridge.get_selected_text_with_context(
            SelectionContext(process_name="msedge.exe", captured_at=30.0)
        )

    clock.value = 40.0
    bridge.ingest_payload(_payload("old gesture"), received_at=39.0)
    with pytest.raises(SelectionError, match="predates current gesture"):
        bridge.get_selected_text_with_context(
            SelectionContext(process_name="chrome.exe", captured_at=40.0)
        )


def test_bridge_http_receiver_accepts_extension_service_worker_payload() -> None:
    bridge = BrowserSelectionBridge(host="127.0.0.1", port=0)
    assert bridge.start()
    try:
        body = json.dumps(_payload("posted through loopback")).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{bridge.bound_port}/v1/selection",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                BRIDGE_HEADER_NAME: BRIDGE_HEADER_VALUE,
                "Origin": "chrome-extension://abcdefghijklmnop",
            },
        )
        with urlopen(request, timeout=1.0) as response:
            assert response.status == 204

        assert bridge.get_selected_text_with_context(
            SelectionContext(process_name="chrome.exe")
        ) == SelectedText("posted through loopback", provider="browser_bridge")
    finally:
        bridge.stop()


def test_bridge_http_receiver_rejects_requests_without_bridge_header() -> None:
    bridge = BrowserSelectionBridge(host="127.0.0.1", port=0)
    assert bridge.start()
    try:
        request = Request(
            f"http://127.0.0.1:{bridge.bound_port}/v1/selection",
            data=json.dumps(_payload()).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=1.0)
        assert caught.value.code == 403
        assert bridge.status_snapshot().has_extension_activity is False
    finally:
        bridge.stop()
