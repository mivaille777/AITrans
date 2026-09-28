from __future__ import annotations

from functools import lru_cache

from app.infrastructure.paths import bundle_root


@lru_cache(maxsize=1)
def get_app_version() -> str:
    version_file = bundle_root() / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0+unknown"
    return value or "0.0.0+unknown"


__all__ = ["get_app_version"]
