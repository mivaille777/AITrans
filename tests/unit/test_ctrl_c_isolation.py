"""Regression tests ensuring AITranslator never owns the user's Ctrl+C."""

from __future__ import annotations

import pytest

from dataclasses import dataclass

from app.selection.clipboard_provider import ClipboardSelectionProvider
from app.selection.copy_command import CopyCommandAdapter


class FakeClipboard:
    def __init__(self) -> None:
        self.text = "before capture"
        self.token = 1
        self.restore_calls = 0

    def snapshot(self):
        return self.text, self.token

    def read_text(self) -> str:
        return self.text

    def write_text(self, text: str) -> None:
        self.text = text
        self.token += 1

    def get_change_token(self) -> int:
        return self.token

    def restore(self, snapshot) -> None:
        self.restore_calls += 1
        self.text, self.token = snapshot


class FakeCopy:
    def __init__(self, clipboard: FakeClipboard) -> None:
        self.clipboard = clipboard
        self.send_calls = 0

    def send_copy(self) -> None:
        self.send_calls += 1
        self.clipboard.text = "selected text"
        self.clipboard.token += 1


class UserCopyDuringSafetyWait(FakeCopy):
    """Model a real Ctrl+C that lands while AITranslator waits for Ctrl-up."""

    def __init__(self, clipboard: FakeClipboard) -> None:
        super().__init__(clipboard)
        self.wait_calls = 0

    def wait_until_safe(self) -> bool:
        self.wait_calls += 1
        if self.wait_calls == 1:
            self.clipboard.text = "user copied this"
            self.clipboard.token += 1
        return True


@dataclass
class FakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration


def test_newer_user_copy_is_never_overwritten_by_cleanup() -> None:
    clipboard = FakeClipboard()

    def sleeper(_duration: float) -> None:
        # The restore guard represents the small cleanup window. Simulate the
        # user pressing Ctrl+C there after AITranslator captured the selection.
        if clipboard.text == "selected text":
            clipboard.text = "user copied this later"
            clipboard.token += 1

    copy = FakeCopy(clipboard)
    provider = ClipboardSelectionProvider(
        clipboard,
        copy,
        copy_delay_seconds=0,
        restore_guard_seconds=0.03,
        sleeper=sleeper,
    )

    selected = provider.get_selected_text()

    assert selected.text == "selected text"
    assert clipboard.text == "user copied this later"
    assert clipboard.restore_calls == 0


def test_user_ctrl_c_during_safety_wait_wins_without_synthetic_copy() -> None:
    clipboard = FakeClipboard()
    copy = UserCopyDuringSafetyWait(clipboard)
    provider = ClipboardSelectionProvider(
        clipboard,
        copy,
        copy_delay_seconds=0,
        restore_guard_seconds=0,
    )

    selected = provider.get_selected_text()

    assert selected.text == "user copied this"
    assert copy.wait_calls == 1
    assert copy.send_calls == 0
    assert clipboard.text == "user copied this"
    assert clipboard.restore_calls == 0


def test_copy_adapter_waits_for_physical_ctrl_release_before_injection() -> None:
    clock = FakeClock()
    events: list[tuple[int, int, int, int]] = []
    ctrl_down = {"value": True}

    def read_key_state(virtual_key: int) -> int:
        if virtual_key == 0x11 and ctrl_down["value"]:
            return 0x8000
        return 0

    def release_during_sleep(duration: float) -> None:
        clock.sleep(duration)
        ctrl_down["value"] = False

    adapter = CopyCommandAdapter(
        keybd_event=lambda vk, scan, flags, extra: events.append(
            (vk, scan, flags, extra)
        ),
        key_state_reader=read_key_state,
        platform_name="win32",
        clock=clock,
        sleeper=release_during_sleep,
        key_state_poll_seconds=0.01,
        key_release_timeout_seconds=0.2,
    )

    adapter.send_copy()

    assert adapter.last_wait_had_conflict is True
    assert clock.value >= 0.01
    assert events == [
        (0x11, 0, 0, 0),
        (0x43, 0, 0, 0),
        (0x43, 0, 0x0002, 0),
        (0x11, 0, 0x0002, 0),
    ]


def test_copy_adapter_never_injects_when_physical_ctrl_remains_down() -> None:
    events: list[tuple[int, int, int, int]] = []
    adapter = CopyCommandAdapter(
        keybd_event=lambda vk, scan, flags, extra: events.append(
            (vk, scan, flags, extra)
        ),
        key_state_reader=lambda virtual_key: 0x8000 if virtual_key == 0x11 else 0,
        platform_name="win32",
        key_release_timeout_seconds=0,
    )

    with pytest.raises(RuntimeError, match="busy"):
        adapter.send_copy()

    assert events == []
