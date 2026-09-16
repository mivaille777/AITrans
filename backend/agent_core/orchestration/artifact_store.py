from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from backend.models.agent_artifacts import Artifact, artifact_from_payload


ARTIFACT_STORE_SCHEMA_VERSION = 1


class ArtifactConflictError(ValueError):
    pass


def _default_database_path() -> Path:
    explicit = str(os.getenv("AITRANS_AGENT_ARTIFACT_DB", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    data_root = str(os.getenv("AITRANS_DATA_ROOT", "") or "").strip()
    if data_root:
        return (Path(data_root).expanduser().resolve() / "agent_artifacts.sqlite3")

    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / "data" / "agent_artifacts.sqlite3"


class SQLiteArtifactStore:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path or _default_database_path()).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self, target_version: int | None = None) -> int:
        requested = ARTIFACT_STORE_SCHEMA_VERSION if target_version is None else int(target_version)
        if requested != ARTIFACT_STORE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported artifact store schema version: {requested}"
            )
        with self._lock, self._connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > ARTIFACT_STORE_SCHEMA_VERSION:
                raise RuntimeError(
                    f"artifact store schema {current} is newer than supported "
                    f"{ARTIFACT_STORE_SCHEMA_VERSION}"
                )
            if current < 1:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS artifact_versions (
                        artifact_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        producer_task_id TEXT NOT NULL,
                        scope_ref TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        revoked_at TEXT NOT NULL DEFAULT '',
                        revocation_reason TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (artifact_id, version)
                    );
                    CREATE INDEX IF NOT EXISTS idx_artifact_versions_scope
                        ON artifact_versions(scope_ref, artifact_id, version);
                    CREATE INDEX IF NOT EXISTS idx_artifact_versions_task
                        ON artifact_versions(producer_task_id, artifact_id, version);
                    PRAGMA user_version = 1;
                    """
                )
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def put(self, artifact: Artifact) -> Artifact:
        payload = artifact.model_dump(mode="json")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT content_hash, payload_json
                FROM artifact_versions
                WHERE artifact_id = ? AND version = ?
                """,
                (artifact.artifact_id, artifact.version),
            ).fetchone()
            if row is not None:
                if str(row["content_hash"]) != artifact.content_hash:
                    raise ArtifactConflictError(
                        "artifact version already exists with a different content hash"
                    )
                return artifact_from_payload(json.loads(str(row["payload_json"])))

            connection.execute(
                """
                INSERT INTO artifact_versions (
                    artifact_id, version, kind, producer_task_id, scope_ref,
                    content_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.version,
                    artifact.kind.value,
                    artifact.producer_task_id,
                    artifact.scope_ref,
                    artifact.content_hash,
                    serialized,
                    artifact.created_at.isoformat(),
                ),
            )
        return artifact.model_copy(deep=True)

    def get(
        self,
        artifact_id: str,
        version: int,
        *,
        include_revoked: bool = False,
    ) -> Artifact | None:
        condition = "" if include_revoked else "AND revoked_at = ''"
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT payload_json
                FROM artifact_versions
                WHERE artifact_id = ? AND version = ? {condition}
                """,
                (str(artifact_id), int(version)),
            ).fetchone()
        if row is None:
            return None
        return artifact_from_payload(json.loads(str(row["payload_json"])))

    def list_versions(
        self,
        artifact_id: str,
        *,
        include_revoked: bool = False,
    ) -> tuple[Artifact, ...]:
        condition = "" if include_revoked else "AND revoked_at = ''"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json
                FROM artifact_versions
                WHERE artifact_id = ? {condition}
                ORDER BY version ASC
                """,
                (str(artifact_id),),
            ).fetchall()
        return tuple(
            artifact_from_payload(json.loads(str(row["payload_json"])))
            for row in rows
        )

    def revoke(
        self,
        artifact_id: str,
        version: int,
        *,
        reason: str,
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE artifact_versions
                SET revoked_at = ?, revocation_reason = ?
                WHERE artifact_id = ? AND version = ? AND revoked_at = ''
                """,
                (now, str(reason or ""), str(artifact_id), int(version)),
            )
            return cursor.rowcount > 0


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, int], Artifact] = {}
        self._revoked: dict[tuple[str, int], str] = {}
        self._lock = RLock()

    def migrate(self, target_version: int | None = None) -> int:
        requested = ARTIFACT_STORE_SCHEMA_VERSION if target_version is None else int(target_version)
        if requested != ARTIFACT_STORE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported artifact store schema version: {requested}"
            )
        return ARTIFACT_STORE_SCHEMA_VERSION

    def put(self, artifact: Artifact) -> Artifact:
        key = (artifact.artifact_id, artifact.version)
        with self._lock:
            previous = self._items.get(key)
            if previous is not None:
                if previous.content_hash != artifact.content_hash:
                    raise ArtifactConflictError(
                        "artifact version already exists with a different content hash"
                    )
                return previous.model_copy(deep=True)
            self._items[key] = artifact.model_copy(deep=True)
        return artifact.model_copy(deep=True)

    def get(
        self,
        artifact_id: str,
        version: int,
        *,
        include_revoked: bool = False,
    ) -> Artifact | None:
        key = (str(artifact_id), int(version))
        with self._lock:
            if key in self._revoked and not include_revoked:
                return None
            value = self._items.get(key)
            return value.model_copy(deep=True) if value is not None else None

    def list_versions(
        self,
        artifact_id: str,
        *,
        include_revoked: bool = False,
    ) -> tuple[Artifact, ...]:
        with self._lock:
            values = [
                item.model_copy(deep=True)
                for key, item in self._items.items()
                if key[0] == str(artifact_id)
                and (include_revoked or key not in self._revoked)
            ]
        return tuple(sorted(values, key=lambda item: item.version))

    def revoke(
        self,
        artifact_id: str,
        version: int,
        *,
        reason: str,
    ) -> bool:
        key = (str(artifact_id), int(version))
        with self._lock:
            if key not in self._items or key in self._revoked:
                return False
            self._revoked[key] = str(reason or "")
            return True


def build_artifact_store(
    *,
    temporary: bool = False,
    database_path: str | Path | None = None,
) -> SQLiteArtifactStore | InMemoryArtifactStore:
    if temporary:
        return InMemoryArtifactStore()
    return SQLiteArtifactStore(database_path=database_path)


__all__ = [
    "ARTIFACT_STORE_SCHEMA_VERSION",
    "ArtifactConflictError",
    "InMemoryArtifactStore",
    "SQLiteArtifactStore",
    "build_artifact_store",
]
