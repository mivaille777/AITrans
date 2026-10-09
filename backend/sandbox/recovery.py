"""Recover only resources carrying a verifiable AITrans owner marker."""

from __future__ import annotations
import json
import re
import shutil
import time
from pathlib import Path
from backend.sandbox.ownership import (
    OWNER_PID_LABEL,
    OWNER_STARTED_LABEL,
    owner_alive,
    owner_valid,
    current_owner,
)

_ID = re.compile(r"sb_[a-f0-9]{32}\Z")
MARKER = ".aitrans-owner.json"


def linked(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    )


def mark_directory(root: Path, sandbox_id: str, owner: dict) -> None:
    (root / MARKER).write_text(
        json.dumps({"sandbox_id": sandbox_id, **owner}), encoding="utf-8"
    )


def recover_resources(
    client,
    sandbox_root: Path,
    artifact_root: Path,
    *,
    retention_days: int = 7,
    completed_ids: set[str] | None = None,
) -> dict:
    result = {"removed": [], "failed": [], "skipped": []}
    local_owner = current_owner()

    def completed_here(sid, owner):
        return (
            sid in (completed_ids or set())
            and int(owner["pid"]) == local_owner["pid"]
            and abs(float(owner["started"]) - local_owner["started"]) < 0.01
        )

    for collection, containers in ((client.containers, True), (client.networks, False)):
        for resource in collection.list(
            filters={"label": "com.aitrans.sandbox=true"},
            **({"all": True} if containers else {}),
        ):
            labels = resource.attrs.get("Config", {}).get(
                "Labels", {}
            ) or resource.attrs.get("Labels", {})
            sid = labels.get("com.aitrans.sandbox_id", "")
            if (
                not _ID.fullmatch(sid)
                or not labels.get(OWNER_PID_LABEL)
                or not labels.get(OWNER_STARTED_LABEL)
            ):
                result["skipped"].append(sid if _ID.fullmatch(sid) else getattr(resource, "name", sid))
                continue
            owner = {
                "pid": labels[OWNER_PID_LABEL],
                "started": labels[OWNER_STARTED_LABEL],
            }
            if not owner_valid(owner):
                result["skipped"].append(sid)
                continue
            if owner_alive(owner) and not completed_here(sid, owner):
                continue
            try:
                resource.remove(**({"force": True} if containers else {}))
                result["removed"].append(sid)
            except Exception:
                result["failed"].append(sid)
    for root, artifacts in (
        (sandbox_root, False),
        (artifact_root, True),
        (artifact_root / "workspace_changes", True),
    ):
        if not root.is_dir() or linked(root):
            continue
        for directory in root.iterdir():
            if (
                not _ID.fullmatch(directory.name)
                or linked(directory)
                or not directory.is_dir()
            ):
                continue
            marker = directory / MARKER
            try:
                if linked(marker) or marker.stat().st_size > 2048:
                    continue
                owner = json.loads(marker.read_text(encoding="utf-8"))
                if owner.get("sandbox_id") != directory.name or not owner_valid(owner):
                    continue
                if (
                    artifacts
                    and time.time() - float(owner["created"]) < retention_days * 86400
                ):
                    continue
                if (
                    not artifacts
                    and owner_alive(owner)
                    and not completed_here(directory.name, owner)
                ):
                    continue
                resolved = directory.resolve(strict=True)
                if resolved.parent != root.resolve(strict=True):
                    continue
                shutil.rmtree(resolved)
                result["removed"].append(directory.name)
            except FileNotFoundError:
                continue
            except Exception:
                result["failed"].append(directory.name)
    return result
