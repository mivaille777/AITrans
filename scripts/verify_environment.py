"""Verify the Python and third-party dependencies required by the app."""

from __future__ import annotations

import importlib
import platform
import sys
from collections.abc import Iterable


def _import_status(module_names: Iterable[str]) -> tuple[bool, str]:
    errors: list[str] = []
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - exact SDK errors vary
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")
        else:
            return True, module_name

    return False, "; ".join(errors)


def _windows_version() -> str:
    system_name = platform.system()
    if system_name != "Windows":
        return f"{system_name} {platform.release()} (non-Windows)"

    version = sys.getwindowsversion()
    return (
        f"{platform.platform()} "
        f"(major={version.major}, minor={version.minor}, build={version.build})"
    )


def main() -> int:
    print(f"Python version: {platform.python_version()}")
    print(f"Windows version: {_windows_version()}")

    checks = [
        ("pywin32", ("win32com.client", "win32api")),
        ("pynput", ("pynput",)),
        ("cachetools", ("cachetools",)),
        ("certifi", ("certifi",)),
        ("uiautomation", ("uiautomation",)),
    ]

    all_ok = True
    for label, module_names in checks:
        ok, detail = _import_status(module_names)
        if ok:
            print(f"{label} import: OK ({detail})")
        else:
            print(f"{label} import: FAILED ({detail})")
            all_ok = False

    if all_ok:
        print("Environment verification: PASS")
        return 0

    print("Environment verification: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
