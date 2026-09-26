"""Explicit, revocable access to user-selected read-only filesystem folders."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.infrastructure.paths import data_root
from backend.sandbox.workspace import (
    MAX_SANDBOX_INPUT_FILE_BYTES,
    MAX_SANDBOX_INPUT_FILES,
    MAX_SANDBOX_TOTAL_INPUT_BYTES,
    SandboxInputFile,
)

MAX_WORKSPACES = 32
MAX_WORKSPACE_ENTRIES = 4096
_HEX_DIGEST_SIZE = 64


class FilesystemWorkspaceError(ValueError):
    """A selected filesystem workspace could not be safely used."""


class FilesystemWorkspaceNotFoundError(FilesystemWorkspaceError):
    pass


class FilesystemWorkspaceUnavailableError(FilesystemWorkspaceError):
    pass


class FilesystemWorkspaceLimitError(FilesystemWorkspaceError):
    pass


class FilesystemWorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    display_name: str
    readable: bool = True
    writable: bool = False
    status: Literal["active", "missing", "revoked"]
    created_at: str
    last_used_at: str


@dataclass(frozen=True, slots=True)
class FilesystemWorkspaceSnapshot:
    workspace: FilesystemWorkspaceRecord
    input_files: tuple[SandboxInputFile, ...]
    manifest: tuple[dict[str, object], ...]


class FilesystemWorkspaceService:
    """Persist opaque workspace IDs while keeping host paths server-side."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(
            database_path
            if database_path is not None
            else data_root() / "runtime" / "filesystem_workspaces.sqlite3"
        ).expanduser().resolve()
        self._init_lock = Lock()
        self._initialized = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self._initialize()
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(
                parents=True,
                exist_ok=True,
                mode=0o700,
            )
            connection = sqlite3.connect(self.database_path, timeout=5.0)
            try:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS filesystem_workspaces (
                        workspace_id TEXT PRIMARY KEY,
                        root_path TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('active', 'revoked')),
                        created_at TEXT NOT NULL,
                        last_used_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS ix_filesystem_workspaces_last_used "
                    "ON filesystem_workspaces(last_used_at DESC)"
                )
                connection.commit()
            finally:
                connection.close()
            if os.name != "nt":
                self.database_path.chmod(0o600)
            self._initialized = True

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    def create(self, raw_path: str) -> FilesystemWorkspaceRecord:
        candidate_text = str(raw_path or "").strip()
        if not candidate_text or len(candidate_text) > 4096:
            raise FilesystemWorkspaceUnavailableError(
                "Selected filesystem workspace is unavailable."
            )
        candidate = Path(candidate_text).expanduser()
        if not candidate.is_absolute():
            raise FilesystemWorkspaceUnavailableError(
                "Selected filesystem workspace must be an absolute folder path."
            )
        try:
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise FilesystemWorkspaceUnavailableError(
                    "Selected filesystem workspace must be a regular folder."
                )
            root = candidate.resolve(strict=True)
            if root != candidate.absolute():
                # Resolve paths before storing them, but reject a root reached
                # through a symbolic link so its target cannot silently change.
                raise FilesystemWorkspaceUnavailableError(
                    "Selected filesystem workspace is unavailable."
                )
        except FilesystemWorkspaceError:
            raise
        except (OSError, RuntimeError) as exc:
            raise FilesystemWorkspaceUnavailableError(
                "Selected filesystem workspace is unavailable."
            ) from exc

        display_name = root.name or root.anchor.rstrip("\\/") or "Filesystem Workspace"
        now = self._timestamp()
        with self._connection() as connection:
            active_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM filesystem_workspaces WHERE status = 'active'"
                ).fetchone()[0]
            )
            if active_count >= MAX_WORKSPACES:
                raise FilesystemWorkspaceLimitError(
                    "The maximum number of active filesystem workspaces has been reached."
                )
            workspace_id = f"fsw_{uuid4().hex}"
            connection.execute(
                """INSERT INTO filesystem_workspaces
                   (workspace_id, root_path, display_name, status, created_at, last_used_at)
                   VALUES (?, ?, ?, 'active', ?, ?)""",
                (workspace_id, str(root), display_name, now, now),
            )
        return FilesystemWorkspaceRecord(
            workspace_id=workspace_id,
            display_name=display_name,
            status="active",
            created_at=now,
            last_used_at=now,
        )

    def list(self) -> list[FilesystemWorkspaceRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT workspace_id, root_path, display_name, status,
                          created_at, last_used_at
                   FROM filesystem_workspaces ORDER BY last_used_at DESC"""
            ).fetchall()
        return [self._public_record(row) for row in rows]

    def get(self, workspace_id: str) -> FilesystemWorkspaceRecord:
        row = self._get_row(workspace_id)
        if row is None:
            raise FilesystemWorkspaceNotFoundError("Filesystem workspace not found.")
        return self._public_record(row)

    def revoke(self, workspace_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE filesystem_workspaces SET status = 'revoked' WHERE workspace_id = ?",
                (str(workspace_id or "").strip(),),
            )
        return cursor.rowcount > 0

    def snapshot(self, workspace_id: str) -> FilesystemWorkspaceSnapshot:
        row = self._get_row(workspace_id)
        if row is None:
            raise FilesystemWorkspaceNotFoundError("Filesystem workspace not found.")
        if row["status"] != "active":
            raise FilesystemWorkspaceUnavailableError(
                "Filesystem workspace access has been revoked."
            )

        root = Path(str(row["root_path"]))
        try:
            root_stat = root.lstat()
            if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
                raise FilesystemWorkspaceUnavailableError(
                    "Filesystem workspace is unavailable."
                )
            resolved_root = root.resolve(strict=True)
            if resolved_root != root:
                raise FilesystemWorkspaceUnavailableError(
                    "Filesystem workspace is unavailable."
                )
        except FilesystemWorkspaceError:
            raise
        except (OSError, RuntimeError) as exc:
            raise FilesystemWorkspaceUnavailableError(
                "Filesystem workspace is unavailable."
            ) from exc

        input_files: list[SandboxInputFile] = []
        manifest: list[dict[str, object]] = []
        total_bytes = 0
        total_entries = 0
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                resolved_directory = directory.resolve(strict=True)
                if not self._within_root(resolved_directory, resolved_root):
                    continue
                with os.scandir(directory) as scan:
                    entries = sorted(scan, key=lambda item: item.name)
            except OSError as exc:
                raise FilesystemWorkspaceUnavailableError(
                    "Filesystem workspace could not be read."
                ) from exc
            for entry in entries:
                try:
                    total_entries += 1
                    if total_entries > MAX_WORKSPACE_ENTRIES:
                        raise FilesystemWorkspaceLimitError(
                            "Filesystem workspace contains too many filesystem entries."
                        )
                    path = Path(entry.path)
                    metadata = path.lstat()
                    if stat.S_ISLNK(metadata.st_mode):
                        continue
                    resolved_path = path.resolve(strict=True)
                    if not self._within_root(resolved_path, resolved_root):
                        continue
                    relative = PurePosixPath(path.relative_to(root).as_posix())
                    if ".git" in relative.parts or self._is_workspace_database(path):
                        continue
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(path)
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    if metadata.st_size > MAX_SANDBOX_INPUT_FILE_BYTES:
                        raise FilesystemWorkspaceLimitError(
                            "A filesystem workspace file exceeds the input size limit."
                        )
                    if len(input_files) >= MAX_SANDBOX_INPUT_FILES:
                        raise FilesystemWorkspaceLimitError(
                            "Filesystem workspace contains too many input files."
                        )
                    total_bytes += metadata.st_size
                    if total_bytes > MAX_SANDBOX_TOTAL_INPUT_BYTES:
                        raise FilesystemWorkspaceLimitError(
                            "Filesystem workspace exceeds the total input size limit."
                        )
                    size_bytes, digest = self._read_digest(path, metadata)
                    if size_bytes != metadata.st_size:
                        raise FilesystemWorkspaceUnavailableError(
                            "A filesystem workspace file changed while being read."
                        )
                    relative_path = relative.as_posix()
                    file_id = "fsw_" + hashlib.sha256(
                        relative_path.encode("utf-8")
                    ).hexdigest()[:32]
                    input_files.append(
                        SandboxInputFile(
                            file_id=file_id,
                            display_name=path.name,
                            source_path=path,
                            relative_path=relative_path,
                            expected_size_bytes=size_bytes,
                            expected_sha256=digest,
                        )
                    )
                    manifest.append(
                        {
                            "file_id": file_id,
                            "relative_path": relative_path,
                            "size_bytes": size_bytes,
                            "sha256": digest,
                            "source": "workspace",
                        }
                    )
                except FilesystemWorkspaceError:
                    raise
                except (OSError, RuntimeError, ValueError) as exc:
                    raise FilesystemWorkspaceUnavailableError(
                        "Filesystem workspace could not be inspected safely."
                    ) from exc

        now = self._timestamp()
        with self._connection() as connection:
            connection.execute(
                "UPDATE filesystem_workspaces SET last_used_at = ? "
                "WHERE workspace_id = ? AND status = 'active'",
                (now, str(workspace_id or "").strip()),
            )
        record = FilesystemWorkspaceRecord(
            workspace_id=str(row["workspace_id"]),
            display_name=str(row["display_name"]),
            status="active",
            created_at=str(row["created_at"]),
            last_used_at=now,
        )
        return FilesystemWorkspaceSnapshot(
            workspace=record,
            input_files=tuple(input_files),
            manifest=tuple(manifest),
        )

    def _is_workspace_database(self, path: Path) -> bool:
        database_names = {
            self.database_path.name,
            f"{self.database_path.name}-wal",
            f"{self.database_path.name}-shm",
            f"{self.database_path.name}-journal",
        }
        return path.parent.resolve(strict=False) == self.database_path.parent and path.name in database_names

    @staticmethod
    def _within_root(path: Path, root: Path) -> bool:
        return path == root or root in path.parents

    @staticmethod
    def _read_digest(path: Path, initial_stat: os.stat_result) -> tuple[int, str]:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode):
                raise FilesystemWorkspaceUnavailableError(
                    "Filesystem workspace files must be regular files."
                )
            if (
                opened_stat.st_dev != initial_stat.st_dev
                or opened_stat.st_ino != initial_stat.st_ino
            ):
                raise FilesystemWorkspaceUnavailableError(
                    "A filesystem workspace file changed while being read."
                )
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                while chunk := handle.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > MAX_SANDBOX_INPUT_FILE_BYTES:
                        raise FilesystemWorkspaceLimitError(
                            "A filesystem workspace file exceeds the input size limit."
                        )
                    digest.update(chunk)
            final_stat = path.lstat()
            if (
                stat.S_ISLNK(final_stat.st_mode)
                or final_stat.st_size != opened_stat.st_size
                or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
            ):
                raise FilesystemWorkspaceUnavailableError(
                    "A filesystem workspace file changed while being read."
                )
            return size_bytes, digest.hexdigest()
        finally:
            os.close(descriptor)

    def _get_row(self, workspace_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(
                """SELECT workspace_id, root_path, display_name, status,
                          created_at, last_used_at
                   FROM filesystem_workspaces WHERE workspace_id = ?""",
                (str(workspace_id or "").strip(),),
            ).fetchone()

    @staticmethod
    def _public_record(row: sqlite3.Row) -> FilesystemWorkspaceRecord:
        status = str(row["status"])
        root = Path(str(row["root_path"]))
        if status == "active":
            try:
                metadata = root.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    status = "missing"
            except OSError:
                status = "missing"
        return FilesystemWorkspaceRecord(
            workspace_id=str(row["workspace_id"]),
            display_name=str(row["display_name"]),
            status=status,  # type: ignore[arg-type]
            created_at=str(row["created_at"]),
            last_used_at=str(row["last_used_at"]),
        )


__all__ = [
    "FilesystemWorkspaceError",
    "FilesystemWorkspaceLimitError",
    "FilesystemWorkspaceNotFoundError",
    "FilesystemWorkspaceRecord",
    "FilesystemWorkspaceService",
    "FilesystemWorkspaceSnapshot",
    "FilesystemWorkspaceUnavailableError",
]
