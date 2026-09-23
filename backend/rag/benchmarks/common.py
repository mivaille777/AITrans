from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BENCHMARK_ROOT = REPOSITORY_ROOT / "data" / "benchmarks" / "qasper"


def benchmark_root(path: str | Path | None = None) -> Path:
    return Path(path or DEFAULT_BENCHMARK_ROOT).expanduser().resolve()


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination


def read_json(path: str | Path) -> dict[str, Any] | None:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read benchmark manifest: {source}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"benchmark manifest must contain a JSON object: {source}")
    return payload


__all__ = [
    "DEFAULT_BENCHMARK_ROOT",
    "REPOSITORY_ROOT",
    "atomic_write_json",
    "benchmark_root",
    "read_json",
]
