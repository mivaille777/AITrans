"""Read artifacts only through a verified run manifest; never accept host paths."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path

from backend.models.sandbox_debug import SandboxDebugTrace
from backend.services.sandbox_debug_service import SandboxDebugError


def read_artifact(
    trace: SandboxDebugTrace, file_id: str, root: Path
) -> tuple[str, bytes]:
    return read_manifest_artifact(trace.run.sandbox_id, trace.output_files, file_id, root)


def read_manifest_artifact(sandbox_id: str, files, file_id: str, root: Path) -> tuple[str, bytes]:
    item = next((item for item in files if item.file_id == file_id), None)
    if item is None or not re.fullmatch(r"sb_[a-f0-9]{32}", sandbox_id):
        raise SandboxDebugError(
            "artifact_not_found", "Artifact not found.", status_code=404
        )
    parts = item.relative_path.replace("\\", "/").split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise SandboxDebugError(
            "artifact_invalid", "Invalid artifact manifest.", status_code=409
        )
    path = Path(root)
    try:
        # Reject links and Windows reparse points at every component.
        for part in (sandbox_id, *parts):
            path = path / part
            info = path.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("Linked artifact")
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size != item.size_bytes
            or info.st_size > 20 * 1024 * 1024
        ):
            raise ValueError("Invalid artifact size")
        if not path.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError("Artifact escaped root")
        with path.open("rb") as stream:
            data = stream.read(20 * 1024 * 1024 + 1)
        if (
            len(data) != item.size_bytes
            or hashlib.sha256(data).hexdigest() != item.sha256
        ):
            raise ValueError("Artifact changed")
        return parts[-1], data
    except FileNotFoundError as exc:
        raise SandboxDebugError(
            "artifact_expired", "Artifact expired or was removed.", status_code=410
        ) from exc
    except (OSError, ValueError) as exc:
        raise SandboxDebugError(
            "artifact_invalid", "Artifact verification failed.", status_code=409
        ) from exc


def export_report(trace: SandboxDebugTrace, format: str) -> dict:
    if format == "json":
        content = json.dumps(
            trace.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
    else:
        # Fence length exceeds every backtick run in untrusted logs/metadata.
        raw = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, indent=2)
        fence = "`" * max(
            3, 1 + max((len(m.group()) for m in re.finditer(r"`+", raw)), default=0)
        )
        content = f"# Sandbox report\n\nRun: {trace.run.sandbox_id}\n\nStatus: {trace.run.status}\n\nLogs retained: {trace.logs_retained}\n\n{fence}json\n{raw}\n{fence}\n"
    return {
        "filename": f"{trace.run.sandbox_id}.{'json' if format == 'json' else 'md'}",
        "content": content,
        "mime_type": "application/json" if format == "json" else "text/markdown",
    }
