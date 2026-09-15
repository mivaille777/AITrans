"""Mocked clipboard and copy-command tests for Step5."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from pynput import keyboard

from app.models.selection import SelectedText
from app.selection.base import SelectionProvider
from app.selection.clipboard_adapter import ClipboardAdapter
from app.selection.clipboard_provider import ClipboardSelectionProvider
from app.selection.copy_command import CopyCommandAdapter
from app.selection.errors import SelectionError
from app.selection.manager import SelectionManager


@dataclass
class FakeClipboardAdapter:
    current_text: str = "original clipboard"
    token: int = 1
    restore_calls: int = 0

    def snapshot(self):
        return self.current_text, self.token

    def read_text(self) -> str:
        return self.current_text

    def write_text(self, text: str) -> None:
        self.current_text = text
        self.token += 1

    def get_change_token(self) -> int:
        return self.token

    def restore(self, snapshot) -> None:
        self.restore_calls += 1
        self.current_text, self.token = snapshot


class FakeCopyCommand:
    def __init__(self, callback=None, error: Exception | None = None) -> None:
        self.callback = callback
        self.error = error
        self.calls = 0

    def send_copy(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.callback is not None:
            self.callback()


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration


def test_headless_clipboard_adapter_restores_text_and_dib_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unicode_text = 13
    device_independent_bitmap = 8
    contents: dict[int, str | bytes] = {
        unicode_text: "keep this text",
        device_independent_bitmap: b"image-data",
    }

    class FakeWin32Clipboard:
        @staticmethod
        def OpenClipboard() -> None:
            return None

        @staticmethod
        def CloseClipboard() -> None:
            return None

        @staticmethod
        def EnumClipboardFormats(current_format: int) -> int:
            return next((key for key in sorted(contents) if key > current_format), 0)

        @staticmethod
        def GetClipboardData(format_id: int) -> str | bytes:
            return contents[format_id]

        @staticmethod
        def IsClipboardFormatAvailable(format_id: int) -> bool:
            return format_id in contents

        @staticmethod
        def EmptyClipboard() -> None:
            contents.clear()

        @staticmethod
        def SetClipboardData(format_id: int, value: str | bytes) -> None:
            contents[format_id] = value

        @staticmethod
        def GetClipboardSequenceNumber() -> int:
            return 1

    monkeypatch.setitem(sys.modules, "win32clipboard", FakeWin32Clipboard)
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(CF_UNICODETEXT=unicode_text, CF_TEXT=1),
    )
    adapter = ClipboardAdapter(platform_name="win32")

    snapshot = adapter.snapshot()
    adapter.write_text("temporary selection")
    adapter.restore(snapshot)

    assert snapshot.text == "keep this text"
    assert snapshot.formats == (
        (device_independent_bitmap, b"image-data"),
        (unicode_text, "keep this text"),
    )
    assert contents == {
        unicode_text: "keep this text",
        device_independent_bitmap: b"image-data",
    }


def test_clipboard_provider_returns_selected_text_and_restores_clipboard() -> None:
    clipboard = FakeClipboardAdapter()

    def copy_selection() -> None:
        clipboard.current_text = "selected from Notepad"
        clipboard.token += 1

    copy = FakeCopyCommand(callback=copy_selection)
    provider = ClipboardSelectionProvider(
        clipboard,
        copy,
        timeout_seconds=0.2,
    )

    selected = provider.get_selected_text()

    assert selected == SelectedText("selected from Notepad")
    assert copy.calls == 1
    assert clipboard.current_text == "original clipboard"
    assert clipboard.restore_calls == 1


def test_clipboard_provider_accepts_text_change_when_sequence_token_is_stable() -> None:
    clipboard = FakeClipboardAdapter()

    def copy_selection_without_sequence_update() -> None:
        clipboard.current_text = "selection despite stable token"

    provider = ClipboardSelectionProvider(
        clipboard,
        FakeCopyCommand(callback=copy_selection_without_sequence_update),
        copy_delay_seconds=0,
    )

    selected = provider.get_selected_text()

    assert selected.text == "selection despite stable token"
    assert clipboard.current_text == "original clipboard"


def test_clipboard_provider_accepts_selection_equal_to_previous_clipboard() -> None:
    clipboard = FakeClipboardAdapter(current_text="same selected text")

    def copy_selection_without_new_sequence_number() -> None:
        clipboard.current_text = "same selected text"

    provider = ClipboardSelectionProvider(
        clipboard,
        FakeCopyCommand(callback=copy_selection_without_new_sequence_number),
        copy_delay_seconds=0,
    )

    selected = provider.get_selected_text()

    assert selected.text == "same selected text"
    assert clipboard.current_text == "same selected text"


def test_clipboard_provider_retries_copy_when_first_attempt_has_no_effect() -> None:
    clipboard = FakeClipboardAdapter()
    copy_calls = 0

    class RetryingCopyCommand:
        def send_copy(self) -> None:
            nonlocal copy_calls
            copy_calls += 1
            if copy_calls == 2:
                clipboard.current_text = "selection after retry"

    provider = ClipboardSelectionProvider(
        clipboard,
        RetryingCopyCommand(),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
        copy_delay_seconds=0,
        copy_attempts=2,
    )

    selected = provider.get_selected_text()

    assert selected.text == "selection after retry"
    assert copy_calls == 2


def test_clipboard_provider_rejects_empty_selection_and_restores_clipboard() -> None:
    clipboard = FakeClipboardAdapter(current_text="keep me")

    def copy_empty_selection() -> None:
        clipboard.current_text = "   "
        clipboard.token += 1

    provider = ClipboardSelectionProvider(
        clipboard,
        FakeCopyCommand(callback=copy_empty_selection),
        timeout_seconds=0.2,
    )

    with pytest.raises(SelectionError, match="empty"):
        provider.get_selected_text()

    assert clipboard.current_text == "keep me"
    assert clipboard.restore_calls == 1


def test_clipboard_provider_times_out_without_returning_stale_clipboard() -> None:
    clipboard = FakeClipboardAdapter(current_text="old text")
    clock = FakeClock()
    provider = ClipboardSelectionProvider(
        clipboard,
        FakeCopyCommand(),
        timeout_seconds=0.03,
        poll_interval_seconds=0.01,
        clock=clock,
        sleeper=clock.sleep,
    )

    with pytest.raises(SelectionError, match="timeout"):
        provider.get_selected_text()

    assert clipboard.current_text == "old text"
    assert clipboard.restore_calls == 1


def test_clipboard_provider_restores_after_copy_command_error() -> None:
    clipboard = FakeClipboardAdapter(current_text="preserve this")
    provider = ClipboardSelectionProvider(
        clipboard,
        FakeCopyCommand(error=RuntimeError("copy failed")),
    )

    with pytest.raises(SelectionError, match="clipboard selection failed"):
        provider.get_selected_text()

    assert clipboard.current_text == "preserve this"
    assert clipboard.restore_calls == 1


def test_copy_command_adapter_sends_balanced_ctrl_c() -> None:
    controller = MagicMock()
    adapter = CopyCommandAdapter(controller)

    adapter.send_copy()

    assert controller.method_calls == [
        call.press(keyboard.Key.ctrl),
        call.press("c"),
        call.release("c"),
        call.release(keyboard.Key.ctrl),
    ]


def test_copy_command_adapter_uses_balanced_native_windows_events() -> None:
    events: list[tuple[int, int, int, int]] = []

    adapter = CopyCommandAdapter(
        keybd_event=lambda vk, scan, flags, extra: events.append(
            (vk, scan, flags, extra)
        ),
        platform_name="win32",
    )

    adapter.send_copy()

    assert events == [
        (0x11, 0, 0, 0),
        (0x43, 0, 0, 0),
        (0x43, 0, 0x0002, 0),
        (0x11, 0, 0x0002, 0),
    ]


def test_clipboard_provider_waits_before_copying_to_release_hotkey_modifier() -> None:
    clipboard = FakeClipboardAdapter()
    events: list[str] = []

    class OrderedCopyCommand:
        def send_copy(self) -> None:
            events.append("copy")
            clipboard.current_text = "after delay"
            clipboard.token += 1

    def record_sleep(_duration: float) -> None:
        events.append("sleep")

    provider = ClipboardSelectionProvider(
        clipboard,
        OrderedCopyCommand(),
        copy_delay_seconds=0.08,
        sleeper=record_sleep,
    )
    provider.get_selected_text()

    assert events[:2] == ["sleep", "copy"]


def test_native_clipboard_adapter_reads_and_restores_text_without_qt(
    monkeypatch,
) -> None:
    class FakeNativeClipboard:
        text = "original text"

        @classmethod
        def OpenClipboard(cls) -> None:
            return None

        @classmethod
        def CloseClipboard(cls) -> None:
            return None

        @classmethod
        def EnumClipboardFormats(cls, current_format: int) -> int:
            if current_format == 0 and cls.text:
                return 13
            return 0

        @classmethod
        def IsClipboardFormatAvailable(cls, format_id: int) -> bool:
            return format_id == 13

        @classmethod
        def GetClipboardData(cls, _format_id: int) -> str:
            return cls.text

        @classmethod
        def EmptyClipboard(cls) -> None:
            cls.text = ""

        @classmethod
        def SetClipboardData(cls, _format_id: int, text: str) -> None:
            cls.text = text

    monkeypatch.setitem(sys.modules, "win32clipboard", FakeNativeClipboard)
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(CF_UNICODETEXT=13, CF_TEXT=1),
    )

    from app.selection.clipboard_adapter import ClipboardAdapter

    adapter = ClipboardAdapter(
        sequence_number_reader=lambda: 1,
        restore_attempts=1,
        platform_name="win32",
    )
    snapshot = adapter.snapshot()
    adapter.write_text("sentinel")
    assert FakeNativeClipboard.text == "sentinel"
    FakeNativeClipboard.text = "selected text"

    adapter.restore(snapshot)

    assert snapshot.text == "original text"
    assert FakeNativeClipboard.text == "original text"


class FakeProvider(SelectionProvider):
    def get_selected_text(self) -> SelectedText:
        return SelectedText("manager result")


def test_selection_manager_returns_selected_text_from_provider() -> None:
    selected = SelectionManager(provider=FakeProvider()).get_selected_text()

    assert selected == SelectedText("manager result")
