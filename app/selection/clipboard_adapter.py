"""Headless Windows clipboard access for the selection compatibility fallback."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from time import sleep
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ClipboardSnapshot:
    """Restorable Windows clipboard state used by the copy fallback.

    Clipboard formats backed by a Windows handle (for example ``CF_BITMAP``)
    cannot safely outlive an open clipboard handle.  Common text, HTML and DIB
    image formats are returned by pywin32 as ``str`` or ``bytes`` and can be
    restored losslessly.
    """

    formats: tuple[tuple[int, str | bytes], ...] = ()
    text: str = ""


def _read_win32_sequence_number() -> int | None:
    """Read the Windows clipboard sequence number when available."""

    try:
        import win32clipboard

        return int(win32clipboard.GetClipboardSequenceNumber())
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return None


class ClipboardAdapter:
    """Access the Windows clipboard through pywin32 without a GUI toolkit."""

    def __init__(
        self,
        *,
        sequence_number_reader: Callable[[], int | None] | None = None,
        restore_attempts: int = 3,
        restore_delay_seconds: float = 0.05,
        sleeper: Callable[[float], None] | None = None,
        platform_name: str | None = None,
    ) -> None:
        self._sequence_number_reader = (
            sequence_number_reader
            if sequence_number_reader is not None
            else _read_win32_sequence_number
        )
        self._restore_attempts = max(1, int(restore_attempts))
        self._restore_delay_seconds = max(0.0, float(restore_delay_seconds))
        self._sleeper = sleeper or sleep
        self._native_windows = (platform_name or sys.platform) == "win32"

    def snapshot(self) -> ClipboardSnapshot:
        """Capture every directly restorable clipboard format.

        This deliberately avoids taking ownership of handle-backed formats. If
        a clipboard cannot be represented safely, abort before the fallback can
        overwrite a user's clipboard data.
        """

        self._require_windows()

        def read_snapshot(clipboard_module: Any, constants: Any) -> ClipboardSnapshot:
            captured: list[tuple[int, str | bytes]] = []
            unsupported: list[int] = []
            format_id = 0
            while True:
                format_id = int(clipboard_module.EnumClipboardFormats(format_id))
                if format_id == 0:
                    break
                try:
                    value = clipboard_module.GetClipboardData(format_id)
                except Exception:
                    unsupported.append(format_id)
                    continue
                if isinstance(value, (str, bytes)):
                    captured.append((format_id, value))
                else:
                    unsupported.append(format_id)

            if unsupported and not captured:
                raise RuntimeError(
                    "clipboard content cannot be safely preserved for copy fallback"
                )

            text = self._text_from_formats(captured, constants)
            return ClipboardSnapshot(formats=tuple(captured), text=text)

        return self._native_clipboard_call(read_snapshot)

    def read_text(self) -> str:
        """Return current plain text, or an empty string for non-text data."""

        self._require_windows()

        def read_formats(clipboard_module: Any, constants: Any) -> str:
            for format_id, encoding in (
                (constants.CF_UNICODETEXT, "utf-16-le"),
                (constants.CF_TEXT, "mbcs"),
            ):
                try:
                    if not clipboard_module.IsClipboardFormatAvailable(format_id):
                        continue
                    value = clipboard_module.GetClipboardData(format_id)
                except Exception:
                    continue
                if isinstance(value, bytes):
                    value = value.rstrip(b"\x00").decode(encoding, errors="replace")
                return str(value).rstrip("\x00")
            return ""

        return str(self._native_clipboard_call(read_formats))

    def write_text(self, text: str) -> None:
        """Replace the clipboard with plain text and verify the write."""

        normalized_text = str(text)
        self._require_windows()

        def write_text(clipboard_module: Any, constants: Any) -> None:
            clipboard_module.EmptyClipboard()
            if normalized_text:
                clipboard_module.SetClipboardData(
                    constants.CF_UNICODETEXT,
                    normalized_text,
                )

        self._native_clipboard_call(write_text)
        if self.read_text() != normalized_text:
            raise RuntimeError("clipboard write could not be verified")

    def get_change_token(self) -> object:
        """Return a token that changes when clipboard content changes."""

        sequence_number = self._sequence_number_reader()
        return sequence_number if sequence_number is not None else self.read_text()

    def restore(self, snapshot: ClipboardSnapshot) -> None:
        """Restore text, HTML and image data while tolerating clipboard locks."""

        last_error: Exception | None = None
        for attempt in range(self._restore_attempts):
            try:
                self._restore_snapshot(snapshot)
                return
            except Exception as exc:
                last_error = exc
            if attempt + 1 < self._restore_attempts:
                self._sleeper(self._restore_delay_seconds)

        if last_error is not None:
            raise RuntimeError("clipboard restore failed") from last_error
        raise RuntimeError("clipboard restore could not be verified")

    def _restore_snapshot(self, snapshot: ClipboardSnapshot) -> None:
        """Write a captured set of directly restorable clipboard formats."""

        if not snapshot.formats:
            self.write_text(snapshot.text)
            return

        def write_formats(clipboard_module: Any, _constants: Any) -> None:
            clipboard_module.EmptyClipboard()
            for format_id, value in snapshot.formats:
                clipboard_module.SetClipboardData(format_id, value)

        self._native_clipboard_call(write_formats)
        if self.read_text() != snapshot.text:
            raise RuntimeError("clipboard restore could not be verified")

    @staticmethod
    def _text_from_formats(
        formats: list[tuple[int, str | bytes]],
        constants: Any,
    ) -> str:
        for preferred_format, encoding in (
            (constants.CF_UNICODETEXT, "utf-16-le"),
            (constants.CF_TEXT, "mbcs"),
        ):
            for format_id, value in formats:
                if format_id != preferred_format:
                    continue
                if isinstance(value, bytes):
                    return value.rstrip(b"\x00").decode(encoding, errors="replace")
                return value.rstrip("\x00")
        return ""

    def _require_windows(self) -> None:
        if not self._native_windows:
            raise RuntimeError("clipboard selection is only supported on Windows")

    def _native_clipboard_call(
        self,
        operation: Callable[[Any, Any], Any],
    ) -> Any:
        try:
            import win32clipboard
            import win32con
        except (ImportError, AttributeError) as exc:
            raise RuntimeError("pywin32 clipboard support is unavailable") from exc

        last_error: Exception | None = None
        for attempt in range(max(3, self._restore_attempts)):
            opened = False
            try:
                win32clipboard.OpenClipboard()
                opened = True
                return operation(win32clipboard, win32con)
            except Exception as exc:
                last_error = exc
            finally:
                if opened:
                    try:
                        win32clipboard.CloseClipboard()
                    except Exception:
                        pass
            if attempt + 1 < max(3, self._restore_attempts):
                self._sleeper(self._restore_delay_seconds)

        if last_error is not None:
            raise RuntimeError("native clipboard operation failed") from last_error
        raise RuntimeError("native clipboard operation failed")

    save = snapshot
    get_text = read_text
    set_text = write_text
    change_token = get_change_token
