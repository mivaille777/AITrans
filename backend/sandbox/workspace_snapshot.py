"""Stable, content-addressed snapshots for sandbox workspace files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceSnapshotError(ValueError):
    """A workspace could not be represented as a safe regular-file snapshot."""


class WorkspaceSnapshotFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0)
    mode: int = Field(ge=0, le=0o7777)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            "\\" in value
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("Workspace snapshot paths must be safe relative paths.")
        return path.as_posix()


class WorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1, max_length=128)
    files: tuple[WorkspaceSnapshotFile, ...]
    snapshot_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


def create_workspace_snapshot(
    workspace_id: str,
    files: Iterable[WorkspaceSnapshotFile | dict[str, object]],
) -> WorkspaceSnapshot:
    """Build a canonical snapshot hash over path, content, size, and mode."""

    normalized = tuple(
        sorted(
            (
                item
                if isinstance(item, WorkspaceSnapshotFile)
                else WorkspaceSnapshotFile.model_validate(item)
                for item in files
            ),
            key=lambda item: item.relative_path,
        )
    )
    paths = [item.relative_path for item in normalized]
    if len(paths) != len(set(paths)):
        raise WorkspaceSnapshotError("Workspace snapshot contains duplicate paths.")
    encoded = json.dumps(
        [item.model_dump(mode="json") for item in normalized],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return WorkspaceSnapshot(
        workspace_id=workspace_id,
        files=normalized,
        snapshot_hash=hashlib.sha256(encoded).hexdigest(),
    )


def snapshot_directory(
    root: str | Path,
    workspace_id: str,
    *,
    modes: dict[str, int] | None = None,
) -> WorkspaceSnapshot:
    """Hash a directory without following links or accepting special files."""

    root_path = Path(root)
    try:
        root_stat = root_path.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            raise WorkspaceSnapshotError(
                "Workspace snapshot root must be a real folder."
            )
        root_path = root_path.resolve(strict=True)
    except WorkspaceSnapshotError:
        raise
    except (OSError, RuntimeError) as exc:
        raise WorkspaceSnapshotError("Workspace snapshot root is unavailable.") from exc

    snapshots: list[WorkspaceSnapshotFile] = []
    pending = [root_path]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
            for entry in entries:
                path = Path(entry.path)
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise WorkspaceSnapshotError(
                        "Workspace snapshot contains a symbolic link."
                    )
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise WorkspaceSnapshotError(
                        "Workspace snapshot contains an unsupported file type."
                    )
                relative_path = path.relative_to(root_path).as_posix()
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                final_stat = path.lstat()
                if (
                    stat.S_ISLNK(final_stat.st_mode)
                    or not stat.S_ISREG(final_stat.st_mode)
                    or final_stat.st_size != size
                    or final_stat.st_mtime_ns != metadata.st_mtime_ns
                ):
                    raise WorkspaceSnapshotError(
                        "A workspace file changed while it was being snapshotted."
                    )
                snapshots.append(
                    WorkspaceSnapshotFile(
                        relative_path=relative_path,
                        sha256=digest.hexdigest(),
                        size=size,
                        mode=(modes or {}).get(
                            relative_path, stat.S_IMODE(metadata.st_mode)
                        ),
                    )
                )
        except WorkspaceSnapshotError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkspaceSnapshotError(
                "Workspace snapshot could not be inspected safely."
            ) from exc
    return create_workspace_snapshot(workspace_id, snapshots)


__all__ = [
    "WorkspaceSnapshot",
    "WorkspaceSnapshotError",
    "WorkspaceSnapshotFile",
    "create_workspace_snapshot",
    "snapshot_directory",
]
