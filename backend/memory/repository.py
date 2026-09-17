from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.models.memory import MemoryItem, MemoryKind, MemoryStatus

MEMORY_SCHEMA_VERSION = 1


class MemoryConflictError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SQLiteMemoryRepository:
    """Canonical local memory store with immutable versions and revocation."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_state(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_profiles(
                    profile_id TEXT PRIMARY KEY,
                    read_enabled INTEGER NOT NULL DEFAULT 1,
                    write_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_items(
                    item_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES memory_profiles(profile_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_scope
                    ON memory_items(profile_id, workspace_id, status, kind);
                CREATE TABLE IF NOT EXISTS memory_versions(
                    item_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    audience_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, version),
                    FOREIGN KEY(item_id) REFERENCES memory_items(item_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS memory_operations(
                    operation_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_snapshots(
                    snapshot_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    scope_ref TEXT NOT NULL,
                    refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_jobs(
                    job_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL UNIQUE,
                    item_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO memory_state(key, value) VALUES('schema_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(MEMORY_SCHEMA_VERSION),),
            )

    def ensure_profile(self, profile_id: str) -> str:
        profile = str(profile_id).strip()
        if not profile:
            raise ValueError("profile_id is required")
        now = _now()
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO memory_profiles(profile_id, created_at, updated_at) VALUES (?, ?, ?)",
                (profile, now, now),
            )
        return profile

    @staticmethod
    def _item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            item_id=str(row["item_id"]),
            profile_id=str(row["profile_id"]),
            workspace_id=str(row["workspace_id"]),
            kind=MemoryKind(str(row["kind"])),
            status=MemoryStatus(str(row["status"])),
            version=int(row["version"]),
            content=str(row["content"]),
            content_hash=str(row["content_hash"]),
            source_type=str(row["source_type"]),
            source_ref=str(row["source_ref"]),
            audience=json.loads(str(row["audience_json"])),
            metadata=json.loads(str(row["metadata_json"])),
            created_at=str(row["item_created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _select() -> str:
        return """
            SELECT i.item_id, i.profile_id, i.workspace_id, i.kind, i.status,
                   v.version, v.content, v.content_hash, v.source_type, v.source_ref,
                   v.audience_json, v.metadata_json, i.created_at AS item_created_at,
                   i.updated_at
            FROM memory_items i JOIN memory_versions v
              ON v.item_id=i.item_id AND v.version=i.current_version
        """

    def get(self, item_id: str, *, version: int | None = None) -> MemoryItem | None:
        sql = self._select()
        params: tuple[Any, ...]
        if version is None:
            sql += " WHERE i.item_id = ?"
            params = (str(item_id),)
        else:
            sql = sql.replace("v.version=i.current_version", "v.version=?")
            sql += " WHERE i.item_id = ?"
            params = (int(version), str(item_id))
        with closing(self._connect()) as connection:
            row = connection.execute(sql, params).fetchone()
        return self._item(row) if row else None

    def list_active(
        self, *, profile_id: str, workspace_id: str
    ) -> tuple[MemoryItem, ...]:
        sql = (
            self._select()
            + " WHERE i.profile_id=? AND i.status='active' AND (i.workspace_id='' OR i.workspace_id=?) ORDER BY i.updated_at DESC"
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, (profile_id, workspace_id)).fetchall()
        return tuple(self._item(row) for row in rows)

    def list_items(
        self,
        *,
        profile_id: str,
        workspace_id: str | None = None,
        status: MemoryStatus | None = None,
    ) -> tuple[MemoryItem, ...]:
        conditions = ["i.profile_id=?"]
        parameters: list[Any] = [profile_id]
        if workspace_id is not None:
            conditions.append("i.workspace_id=?")
            parameters.append(str(workspace_id))
        if status is not None:
            conditions.append("i.status=?")
            parameters.append(status.value)
        sql = (
            self._select()
            + " WHERE "
            + " AND ".join(conditions)
            + " ORDER BY i.updated_at DESC, i.item_id ASC"
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return tuple(self._item(row) for row in rows)

    def save(
        self,
        *,
        operation_id: str,
        profile_id: str,
        workspace_id: str,
        kind: MemoryKind,
        content: str,
        source_type: str,
        source_ref: str,
        audience: list[str],
        metadata: dict[str, Any],
        status: MemoryStatus,
        item_id: str = "",
        expected_version: int = 0,
    ) -> MemoryItem:
        profile = self.ensure_profile(profile_id)
        operation = str(operation_id).strip()
        text = str(content).strip()
        if not operation or not text or not str(source_ref).strip():
            raise ValueError("operation_id, content and source_ref are required")
        payload_hash = _hash(
            _json(
                {
                    "profile_id": profile,
                    "workspace_id": workspace_id,
                    "kind": kind.value,
                    "content": text,
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "audience": sorted(audience),
                    "metadata": metadata,
                    "status": status.value,
                    "item_id": item_id,
                    "expected_version": expected_version,
                }
            )
        )
        now = _now()
        with self._lock, closing(self._connect()) as connection, connection:
            replay = connection.execute(
                "SELECT * FROM memory_operations WHERE operation_id=?", (operation,)
            ).fetchone()
            if replay:
                if str(replay["payload_hash"]) != payload_hash:
                    raise MemoryConflictError(
                        "operation_id was already used for different memory content"
                    )
                result = self.get(
                    str(replay["item_id"]), version=int(replay["version"])
                )
                if result is None:
                    raise RuntimeError(
                        "memory operation receipt points to missing version"
                    )
                return result
            identifier = str(item_id).strip() or f"mem_{uuid4().hex}"
            current = connection.execute(
                "SELECT current_version, profile_id, workspace_id FROM memory_items WHERE item_id=?",
                (identifier,),
            ).fetchone()
            current_version = int(current["current_version"]) if current else 0
            if current_version != int(expected_version):
                raise MemoryConflictError(
                    f"memory version conflict: expected {expected_version}, current {current_version}"
                )
            version = current_version + 1
            if current is not None and (
                str(current["profile_id"]) != profile
                or str(current["workspace_id"]) != str(workspace_id)
            ):
                raise ValueError("memory item belongs to another profile or scope")
            if current is None:
                connection.execute(
                    "INSERT INTO memory_items(item_id, profile_id, workspace_id, kind, status, current_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identifier,
                        profile,
                        workspace_id,
                        kind.value,
                        status.value,
                        version,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE memory_items SET kind=?, status=?, current_version=?, updated_at=? WHERE item_id=? AND profile_id=?",
                    (kind.value, status.value, version, now, identifier, profile),
                )
                if connection.total_changes < 1:
                    raise ValueError("memory item belongs to another profile")
            connection.execute(
                "INSERT INTO memory_versions(item_id, version, content, content_hash, source_type, source_ref, audience_json, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    version,
                    text,
                    _hash(text),
                    source_type,
                    source_ref,
                    _json(sorted(set(audience))),
                    _json(metadata),
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO memory_operations(operation_id, payload_hash, item_id, version, created_at) VALUES (?, ?, ?, ?, ?)",
                (operation, payload_hash, identifier, version, now),
            )
            connection.execute(
                "INSERT INTO memory_jobs(job_id, operation_id, item_id, version, job_type, created_at) VALUES (?, ?, ?, ?, 'index', ?)",
                (f"mjob_{uuid4().hex}", operation, identifier, version, now),
            )
        result = self.get(identifier)
        assert result is not None
        return result

    def revoke(
        self, *, profile_id: str, item_id: str, expected_version: int
    ) -> MemoryItem:
        current = self.get(item_id)
        if current is None or current.profile_id != profile_id:
            raise ValueError("memory item not found")
        return self.save(
            operation_id=f"forget:{item_id}:{expected_version}",
            profile_id=profile_id,
            workspace_id=current.workspace_id,
            kind=current.kind,
            content=current.content,
            source_type=current.source_type,
            source_ref=current.source_ref,
            audience=current.audience,
            metadata={**current.metadata, "revoked_reason": "user_forget"},
            status=MemoryStatus.REVOKED,
            item_id=item_id,
            expected_version=expected_version,
        )

    def snapshot_for_run(
        self, *, run_id: str, profile_id: str, workspace_id: str, scope_ref: str
    ) -> tuple[str, tuple[MemoryItem, ...]]:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM memory_snapshots WHERE run_id=?", (run_id,)
            ).fetchone()
            if row:
                if (
                    str(row["profile_id"]) != profile_id
                    or str(row["workspace_id"]) != workspace_id
                    or str(row["scope_ref"]) != scope_ref
                ):
                    raise MemoryConflictError("run memory snapshot scope changed")
                refs = json.loads(str(row["refs_json"]))
                items = tuple(
                    item
                    for ref in refs
                    if (
                        item := self.get(
                            str(ref["item_id"]), version=int(ref["version"])
                        )
                    )
                    is not None
                )
                return str(row["snapshot_id"]), items
            items = self.list_active(profile_id=profile_id, workspace_id=workspace_id)
            refs = [
                {
                    "item_id": item.item_id,
                    "version": item.version,
                    "content_hash": item.content_hash,
                }
                for item in items
            ]
            snapshot_id = (
                "ms_"
                + _hash(
                    _json(
                        {
                            "profile": profile_id,
                            "workspace": workspace_id,
                            "scope": scope_ref,
                            "refs": refs,
                        }
                    )
                )[:32]
            )
            connection.execute(
                "INSERT INTO memory_snapshots(snapshot_id, run_id, profile_id, workspace_id, scope_ref, refs_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    run_id,
                    profile_id,
                    workspace_id,
                    scope_ref,
                    _json(refs),
                    _now(),
                ),
            )
        return snapshot_id, items


__all__ = ["MEMORY_SCHEMA_VERSION", "MemoryConflictError", "SQLiteMemoryRepository"]
