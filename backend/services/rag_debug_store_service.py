from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.infrastructure.paths import writable_config_dir
from backend.models.rag_debug import (
    RagDebugCase,
    RagDebugConfigProfile,
    RagDebugDataset,
)
from backend.rag.config import RagConfig


DEFAULT_FILENAME = "rag_debug_studio.sqlite3"
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str, default: object) -> object:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def config_index_fingerprint(config: RagConfig) -> str:
    """Return the portion of a profile that changes persisted index assets."""

    payload = {
        "advanced_parsing": config.advanced_parsing.model_dump(mode="json"),
        "visual_understanding": config.visual_understanding.model_dump(mode="json"),
        "visual_retrieval": config.visual_retrieval.model_dump(mode="json"),
        "chunking": config.chunking.model_dump(mode="json"),
        "semantic_chunking": config.semantic_chunking.model_dump(mode="json"),
        "embedding": config.embedding.model_dump(mode="json"),
        "vector_store": config.vector_store.model_dump(mode="json"),
    }
    encoded = _dump(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


class RagDebugStoreService:
    """Local persistence for RAG tuning profiles and evaluation datasets."""

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path).expanduser().resolve()
            if storage_path is not None
            else writable_config_dir() / DEFAULT_FILENAME
        )
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rag_debug_configs (
                config_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                requires_reindex INTEGER NOT NULL DEFAULT 0,
                index_fingerprint TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_debug_configs_name
                ON rag_debug_configs(name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS rag_debug_datasets (
                dataset_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_debug_datasets_name
                ON rag_debug_datasets(name COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS rag_debug_cases (
                dataset_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                case_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(dataset_id, case_id),
                FOREIGN KEY(dataset_id) REFERENCES rag_debug_datasets(dataset_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_rag_debug_cases_dataset
                ON rag_debug_cases(dataset_id, updated_at DESC);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('rag_debug_schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            self._ensure_schema(connection)

    @staticmethod
    def _config_from_row(row: sqlite3.Row) -> RagDebugConfigProfile:
        config = RagConfig.model_validate(_load(row["config_json"], {}))
        return RagDebugConfigProfile(
            config_id=row["config_id"],
            name=row["name"],
            description=row["description"],
            config=config,
            active=bool(row["active"]),
            requires_reindex=bool(row["requires_reindex"]),
            index_fingerprint=row["index_fingerprint"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _dataset_from_row(row: sqlite3.Row, case_count: int) -> RagDebugDataset:
        return RagDebugDataset(
            dataset_id=row["dataset_id"],
            name=row["name"],
            description=row["description"],
            case_count=case_count,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def ensure_default_config(self, config: RagConfig) -> RagDebugConfigProfile:
        current = self.get_config("default")
        if current is not None:
            return current
        now = _now()
        profile = RagDebugConfigProfile(
            config_id="default",
            name="Default",
            description="Current application RAG settings.",
            config=config,
            active=True,
            index_fingerprint=config_index_fingerprint(config),
            created_at=now,
            updated_at=now,
        )
        self._save_config(profile)
        return profile

    def list_configs(self) -> list[RagDebugConfigProfile]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM rag_debug_configs ORDER BY active DESC, updated_at DESC"
            ).fetchall()
        return [self._config_from_row(row) for row in rows]

    def get_config(self, config_id: str) -> RagDebugConfigProfile | None:
        normalized = str(config_id or "").strip()
        if not normalized:
            return None
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM rag_debug_configs WHERE config_id = ?",
                (normalized,),
            ).fetchone()
        return self._config_from_row(row) if row is not None else None

    def create_config(
        self,
        *,
        name: str,
        description: str,
        config: RagConfig,
        activate: bool = False,
    ) -> RagDebugConfigProfile:
        now = _now()
        profile = RagDebugConfigProfile(
            config_id=f"ragcfg_{uuid4().hex[:16]}",
            name=name.strip(),
            description=description.strip(),
            config=config,
            active=activate,
            index_fingerprint=config_index_fingerprint(config),
            created_at=now,
            updated_at=now,
        )
        self._save_config(profile)
        return profile

    def update_config(
        self,
        config_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        config: RagConfig | None = None,
        activate: bool | None = None,
    ) -> RagDebugConfigProfile | None:
        current = self.get_config(config_id)
        if current is None:
            return None
        next_config = config or current.config
        next_fingerprint = config_index_fingerprint(next_config)
        next_profile = current.model_copy(
            update={
                "name": name.strip() if name is not None else current.name,
                "description": (
                    description.strip()
                    if description is not None
                    else current.description
                ),
                "config": next_config,
                "active": current.active if activate is None else activate,
                "requires_reindex": (
                    current.requires_reindex
                    or next_fingerprint != current.index_fingerprint
                ),
                "index_fingerprint": next_fingerprint,
                "updated_at": _now(),
            }
        )
        self._save_config(next_profile)
        return next_profile

    def activate_config(self, config_id: str) -> RagDebugConfigProfile | None:
        target = self.get_config(config_id)
        if target is None:
            return None
        now = _now()
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("UPDATE rag_debug_configs SET active = 0")
            connection.execute(
                "UPDATE rag_debug_configs SET active = 1, updated_at = ? WHERE config_id = ?",
                (now, config_id),
            )
        return self.get_config(config_id)

    def clear_requires_reindex(self, config_id: str) -> RagDebugConfigProfile | None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE rag_debug_configs SET requires_reindex = 0, updated_at = ? WHERE config_id = ?",
                (_now(), config_id),
            )
        return self.get_config(config_id)

    def delete_config(self, config_id: str) -> bool:
        if config_id == "default":
            return False
        with self._lock, closing(self._connect()) as connection, connection:
            result = connection.execute(
                "DELETE FROM rag_debug_configs WHERE config_id = ?", (config_id,)
            )
        return result.rowcount > 0

    def _save_config(self, profile: RagDebugConfigProfile) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            if profile.active:
                connection.execute("UPDATE rag_debug_configs SET active = 0")
            try:
                connection.execute(
                    """
                    INSERT INTO rag_debug_configs(
                        config_id, name, description, config_json, active,
                        requires_reindex, index_fingerprint, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(config_id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        config_json=excluded.config_json,
                        active=excluded.active,
                        requires_reindex=excluded.requires_reindex,
                        index_fingerprint=excluded.index_fingerprint,
                        updated_at=excluded.updated_at
                    """,
                    (
                        profile.config_id,
                        profile.name,
                        profile.description,
                        _dump(profile.config.model_dump(mode="json")),
                        int(profile.active),
                        int(profile.requires_reindex),
                        profile.index_fingerprint,
                        profile.created_at,
                        profile.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A config profile with this name already exists.") from exc

    def list_datasets(self) -> list[RagDebugDataset]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT d.*, COUNT(c.case_id) AS case_count
                FROM rag_debug_datasets d
                LEFT JOIN rag_debug_cases c ON c.dataset_id = d.dataset_id
                GROUP BY d.dataset_id
                ORDER BY d.updated_at DESC
                """
            ).fetchall()
        return [self._dataset_from_row(row, int(row["case_count"])) for row in rows]

    def get_dataset(self, dataset_id: str) -> RagDebugDataset | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT d.*, COUNT(c.case_id) AS case_count
                FROM rag_debug_datasets d
                LEFT JOIN rag_debug_cases c ON c.dataset_id = d.dataset_id
                WHERE d.dataset_id = ?
                GROUP BY d.dataset_id
                """,
                (dataset_id,),
            ).fetchone()
        return self._dataset_from_row(row, int(row["case_count"])) if row else None

    def create_dataset(self, name: str, description: str = "") -> RagDebugDataset:
        now = _now()
        dataset = RagDebugDataset(
            dataset_id=f"ragds_{uuid4().hex[:16]}",
            name=name.strip(),
            description=description.strip(),
            case_count=0,
            created_at=now,
            updated_at=now,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    "INSERT INTO rag_debug_datasets(dataset_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        dataset.dataset_id,
                        dataset.name,
                        dataset.description,
                        dataset.created_at,
                        dataset.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A dataset with this name already exists.") from exc
        return dataset

    def delete_dataset(self, dataset_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            result = connection.execute(
                "DELETE FROM rag_debug_datasets WHERE dataset_id = ?", (dataset_id,)
            )
        return result.rowcount > 0

    def list_cases(self, dataset_id: str) -> list[RagDebugCase]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT case_json FROM rag_debug_cases WHERE dataset_id = ? ORDER BY updated_at DESC, case_id",
                (dataset_id,),
            ).fetchall()
        return [RagDebugCase.model_validate(_load(row["case_json"], {})) for row in rows]

    def get_case(self, dataset_id: str, case_id: str) -> RagDebugCase | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT case_json FROM rag_debug_cases WHERE dataset_id = ? AND case_id = ?",
                (dataset_id, case_id),
            ).fetchone()
        return RagDebugCase.model_validate(_load(row["case_json"], {})) if row else None

    def save_case(self, dataset_id: str, case: RagDebugCase) -> RagDebugCase:
        if self.get_dataset(dataset_id) is None:
            raise KeyError(dataset_id)
        now = _now()
        saved = case.model_copy(update={"updated_at": case.updated_at or now})
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO rag_debug_cases(dataset_id, case_id, case_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id, case_id) DO UPDATE SET
                    case_json=excluded.case_json,
                    updated_at=excluded.updated_at
                """,
                (
                    dataset_id,
                    saved.case_id,
                    _dump(saved.model_dump(mode="json")),
                    now,
                    saved.updated_at,
                ),
            )
            connection.execute(
                "UPDATE rag_debug_datasets SET updated_at = ? WHERE dataset_id = ?",
                (now, dataset_id),
            )
        return saved

    def delete_case(self, dataset_id: str, case_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            result = connection.execute(
                "DELETE FROM rag_debug_cases WHERE dataset_id = ? AND case_id = ?",
                (dataset_id, case_id),
            )
            if result.rowcount:
                connection.execute(
                    "UPDATE rag_debug_datasets SET updated_at = ? WHERE dataset_id = ?",
                    (_now(), dataset_id),
                )
        return result.rowcount > 0

    def replace_cases(self, dataset_id: str, cases: list[RagDebugCase]) -> RagDebugDataset:
        if self.get_dataset(dataset_id) is None:
            raise KeyError(dataset_id)
        if len({case.case_id for case in cases}) != len(cases):
            raise ValueError("Dataset case_id values must be unique.")
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM rag_debug_cases WHERE dataset_id = ?", (dataset_id,))
            now = _now()
            connection.executemany(
                "INSERT INTO rag_debug_cases(dataset_id, case_id, case_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        dataset_id,
                        case.case_id,
                        _dump(case.model_dump(mode="json")),
                        now,
                        case.updated_at or now,
                    )
                    for case in cases
                ],
            )
            connection.execute(
                "UPDATE rag_debug_datasets SET updated_at = ? WHERE dataset_id = ?",
                (now, dataset_id),
            )
        return self.get_dataset(dataset_id)  # type: ignore[return-value]


__all__ = ["DEFAULT_FILENAME", "RagDebugStoreService", "config_index_fingerprint"]
