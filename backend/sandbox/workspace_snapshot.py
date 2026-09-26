"""Stable, content-addressed snapshots for sandbox workspace files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.sandbox.policy import (
    MAX_WORKSPACE_CHANGED_FILE_BYTES,
    MAX_WORKSPACE_CHANGED_FILES,
    MAX_WORKSPACE_SNAPSHOT_ENTRIES,
    MAX_WORKSPACE_SNAPSHOT_FILE_BYTES,
    MAX_WORKSPACE_SNAPSHOT_FILES,
    MAX_WORKSPACE_SNAPSHOT_TOTAL_BYTES,
    MAX_WORKSPACE_TOTAL_CHANGED_BYTES,
)

_INVALID_COMPONENT_CHARACTERS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


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
            or ":" in value
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("Workspace snapshot paths must be safe relative paths.")
        for part in path.parts:
            stem = part.split(".", 1)[0].upper()
            if (
                len(part) > 255
                or part.endswith((" ", "."))
                or any(
                    ord(character) < 32 or character in _INVALID_COMPONENT_CHARACTERS
                    for character in part
                )
                or stem in _WINDOWS_RESERVED_NAMES
            ):
                raise ValueError(
                    "Workspace snapshot paths must be safe relative paths."
                )
        return path.as_posix()


class WorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1, max_length=128)
    files: tuple[WorkspaceSnapshotFile, ...]
    snapshot_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class WorkspaceChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["create", "modify", "delete"]
    path: str = Field(min_length=1, max_length=1024)
    before_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )
    after_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )
    size_before: int | None = Field(default=None, ge=0)
    size_after: int | None = Field(default=None, ge=0)
    mode_before: int | None = Field(default=None, ge=0, le=0o7777)
    mode_after: int | None = Field(default=None, ge=0, le=0o7777)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return WorkspaceSnapshotFile.validate_relative_path(value)

    @model_validator(mode="after")
    def validate_operation_fields(self) -> WorkspaceChange:
        before_exists = all(
            value is not None
            for value in (self.before_sha256, self.size_before, self.mode_before)
        )
        after_exists = all(
            value is not None
            for value in (self.after_sha256, self.size_after, self.mode_after)
        )
        if self.operation == "create" and (
            self.before_sha256 is not None
            or self.size_before is not None
            or self.mode_before is not None
            or not after_exists
        ):
            raise ValueError("Create changes require only after-file metadata.")
        if self.operation == "modify" and not (before_exists and after_exists):
            raise ValueError("Modify changes require before and after metadata.")
        if self.operation == "delete" and (
            not before_exists
            or self.after_sha256 is not None
            or self.size_after is not None
            or self.mode_after is not None
        ):
            raise ValueError("Delete changes require only before-file metadata.")
        return self


class WorkspaceChangeSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sandbox_id: str = Field(min_length=1, max_length=80)
    workspace_id: str = Field(min_length=1, max_length=128)
    base_snapshot_hash: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )
    changes: tuple[WorkspaceChange, ...]
    changeset_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


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
    entry_count = 0
    total_bytes = 0
    mode_overrides = modes or {}
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = []
                for entry in scan:
                    entry_count += 1
                    if entry_count > MAX_WORKSPACE_SNAPSHOT_ENTRIES:
                        raise WorkspaceSnapshotError(
                            "Workspace snapshot contains too many entries."
                        )
                    entries.append(entry)
            entries.sort(key=lambda entry: entry.name)
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
                if len(snapshots) >= MAX_WORKSPACE_SNAPSHOT_FILES:
                    raise WorkspaceSnapshotError(
                        "Workspace snapshot contains too many files."
                    )
                if metadata.st_size > MAX_WORKSPACE_SNAPSHOT_FILE_BYTES:
                    raise WorkspaceSnapshotError(
                        "A workspace snapshot file exceeds the size limit."
                    )
                relative_path = path.relative_to(root_path).as_posix()
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        if size > MAX_WORKSPACE_SNAPSHOT_FILE_BYTES:
                            raise WorkspaceSnapshotError(
                                "A workspace snapshot file exceeds the size limit."
                            )
                        if total_bytes + size > MAX_WORKSPACE_SNAPSHOT_TOTAL_BYTES:
                            raise WorkspaceSnapshotError(
                                "Workspace snapshot exceeds the total size limit."
                            )
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
                        mode=mode_overrides.get(
                            relative_path, stat.S_IMODE(metadata.st_mode)
                        ),
                    )
                )
                total_bytes += size
        except WorkspaceSnapshotError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkspaceSnapshotError(
                "Workspace snapshot could not be inspected safely."
            ) from exc
    return create_workspace_snapshot(workspace_id, snapshots)


def create_workspace_changeset(
    base: WorkspaceSnapshot,
    current: WorkspaceSnapshot,
    *,
    sandbox_id: str,
) -> WorkspaceChangeSet:
    """Compare the editable copy to its base and enforce P0 diff limits."""

    if base.workspace_id != current.workspace_id:
        raise WorkspaceSnapshotError("Workspace snapshot IDs do not match.")
    before_files = {item.relative_path: item for item in base.files}
    after_files = {item.relative_path: item for item in current.files}
    changes: list[WorkspaceChange] = []
    for path in sorted(before_files.keys() | after_files.keys()):
        before = before_files.get(path)
        after = after_files.get(path)
        if (
            before is not None
            and after is not None
            and (
                before.sha256 == after.sha256
                and before.size == after.size
                and before.mode == after.mode
            )
        ):
            continue
        if is_protected_workspace_path(path):
            raise WorkspaceSnapshotError(
                "Sandbox changes include a protected workspace path."
            )
        if before is None:
            operation: Literal["create", "modify", "delete"] = "create"
        elif after is None:
            operation = "delete"
        else:
            operation = "modify"
        changes.append(
            WorkspaceChange(
                operation=operation,
                path=path,
                before_sha256=before.sha256 if before else None,
                after_sha256=after.sha256 if after else None,
                size_before=before.size if before else None,
                size_after=after.size if after else None,
                mode_before=before.mode if before else None,
                mode_after=after.mode if after else None,
            )
        )

    if len(changes) > MAX_WORKSPACE_CHANGED_FILES:
        raise WorkspaceSnapshotError("Sandbox changed too many workspace files.")
    total_changed_bytes = 0
    for change in changes:
        changed_size = max(change.size_before or 0, change.size_after or 0)
        if changed_size > MAX_WORKSPACE_CHANGED_FILE_BYTES:
            raise WorkspaceSnapshotError(
                "A changed workspace file exceeds the size limit."
            )
        total_changed_bytes += changed_size
    if total_changed_bytes > MAX_WORKSPACE_TOTAL_CHANGED_BYTES:
        raise WorkspaceSnapshotError(
            "Sandbox workspace changes exceed the total size limit."
        )

    provisional = WorkspaceChangeSet(
        sandbox_id=sandbox_id,
        workspace_id=base.workspace_id,
        base_snapshot_hash=base.snapshot_hash,
        changes=tuple(changes),
        changeset_hash="0" * 64,
    )
    return provisional.model_copy(
        update={"changeset_hash": calculate_changeset_hash(provisional)}
    )


def calculate_changeset_hash(changeset: WorkspaceChangeSet) -> str:
    payload = changeset.model_dump(mode="json", exclude={"changeset_hash"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_protected_workspace_path(value: str) -> bool:
    """Return whether a path is excluded from sandbox read/apply access."""

    parts = tuple(part.casefold() for part in PurePosixPath(value).parts)
    if ".git" in parts:
        return True
    if any(part == ".env" or part.startswith(".env.") for part in parts):
        return True
    name = parts[-1] if parts else ""
    return name.endswith((".pem", ".key"))


__all__ = [
    "WorkspaceChange",
    "WorkspaceChangeSet",
    "WorkspaceSnapshot",
    "WorkspaceSnapshotError",
    "WorkspaceSnapshotFile",
    "calculate_changeset_hash",
    "create_workspace_changeset",
    "create_workspace_snapshot",
    "is_protected_workspace_path",
    "snapshot_directory",
]
