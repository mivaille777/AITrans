"""SQLite-backed research workspace organization.

Workspaces intentionally own only lightweight project metadata and stable
associations to existing resources. Documents, research notes and conversations
remain in their original stores so creating or deleting a workspace never
silently duplicates or destroys source data.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.infrastructure.paths import writable_config_dir

DEFAULT_RESEARCH_WORKSPACES_FILENAME = "research_workspaces.sqlite3"
RESEARCH_WORKSPACES_SCHEMA_VERSION = 1
DEFAULT_WORKSPACE_LIMIT = 50
MAX_WORKSPACE_LIMIT = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_storage_path() -> Path:
    return writable_config_dir() / DEFAULT_RESEARCH_WORKSPACES_FILENAME


def _clean(value: object, *, limit: int = 0) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit]
    return text


@dataclass(frozen=True, slots=True)
class ResearchWorkspace:
    workspace_id: str
    name: str
    description: str
    research_goal: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceAssociations:
    document_ids: tuple[str, ...] = ()
    note_ids: tuple[str, ...] = ()
    conversation_ids: tuple[str, ...] = ()


class ResearchWorkspaceStore:
    """Persist project-level research context independently of source stores."""

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path) if storage_path is not None else _default_storage_path()
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
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

            CREATE TABLE IF NOT EXISTS research_workspaces (
                workspace_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                research_goal TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workspace_documents (
                workspace_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, document_id),
                FOREIGN KEY(workspace_id)
                    REFERENCES research_workspaces(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workspace_notes (
                workspace_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, note_id),
                FOREIGN KEY(workspace_id)
                    REFERENCES research_workspaces(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workspace_conversations (
                workspace_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, conversation_id),
                FOREIGN KEY(workspace_id)
                    REFERENCES research_workspaces(workspace_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_research_workspaces_updated_at
                ON research_workspaces(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_workspace_documents_document_id
                ON workspace_documents(document_id);
            CREATE INDEX IF NOT EXISTS idx_workspace_notes_note_id
                ON workspace_notes(note_id);
            CREATE INDEX IF NOT EXISTS idx_workspace_conversations_conversation_id
                ON workspace_conversations(conversation_id);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', ?)",
            (str(RESEARCH_WORKSPACES_SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
        except (OSError, sqlite3.Error):
            # Workspace persistence must not prevent application startup.
            return

    @staticmethod
    def _row_to_workspace(row: tuple[object, ...]) -> ResearchWorkspace:
        return ResearchWorkspace(
            workspace_id=str(row[0]),
            name=str(row[1] or ""),
            description=str(row[2] or ""),
            research_goal=str(row[3] or ""),
            created_at=str(row[4] or ""),
            updated_at=str(row[5] or ""),
        )

    @staticmethod
    def _select_columns() -> str:
        return "workspace_id, name, description, research_goal, created_at, updated_at"

    def create(
        self,
        *,
        name: object,
        description: object = "",
        research_goal: object = "",
    ) -> ResearchWorkspace:
        title = _clean(name, limit=200)
        if not title:
            raise ValueError("Research workspace requires a name.")
        now = _now_iso()
        workspace_id = uuid4().hex
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    connection.execute(
                        """
                        INSERT INTO research_workspaces(
                            workspace_id, name, description, research_goal,
                            created_at, updated_at
                        ) VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (
                            workspace_id,
                            title,
                            _clean(description, limit=4000),
                            _clean(research_goal, limit=8000),
                            now,
                            now,
                        ),
                    )
                    row = connection.execute(
                        f"SELECT {self._select_columns()} FROM research_workspaces "
                        "WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError("Unable to create research workspace.") from exc
        if row is None:
            raise RuntimeError("Research workspace was not persisted.")
        return self._row_to_workspace(row)

    def list_recent(self, *, limit: int = DEFAULT_WORKSPACE_LIMIT) -> tuple[ResearchWorkspace, ...]:
        try:
            bounded_limit = max(1, min(MAX_WORKSPACE_LIMIT, int(limit)))
        except (TypeError, ValueError):
            bounded_limit = DEFAULT_WORKSPACE_LIMIT
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                rows = connection.execute(
                    f"SELECT {self._select_columns()} FROM research_workspaces "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (bounded_limit,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return ()
        return tuple(self._row_to_workspace(row) for row in rows)

    def get(self, workspace_id: object) -> ResearchWorkspace | None:
        identifier = _clean(workspace_id, limit=128)
        if not identifier:
            return None
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    f"SELECT {self._select_columns()} FROM research_workspaces "
                    "WHERE workspace_id = ?",
                    (identifier,),
                ).fetchone()
        except (OSError, sqlite3.Error):
            return None
        return self._row_to_workspace(row) if row is not None else None

    def update(
        self,
        workspace_id: object,
        *,
        name: object,
        description: object = "",
        research_goal: object = "",
    ) -> ResearchWorkspace | None:
        identifier = _clean(workspace_id, limit=128)
        title = _clean(name, limit=200)
        if not identifier:
            return None
        if not title:
            raise ValueError("Research workspace requires a name.")
        now = _now_iso()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    cursor = connection.execute(
                        """
                        UPDATE research_workspaces
                        SET name = ?, description = ?, research_goal = ?, updated_at = ?
                        WHERE workspace_id = ?
                        """,
                        (
                            title,
                            _clean(description, limit=4000),
                            _clean(research_goal, limit=8000),
                            now,
                            identifier,
                        ),
                    )
                    if cursor.rowcount <= 0:
                        return None
                    row = connection.execute(
                        f"SELECT {self._select_columns()} FROM research_workspaces "
                        "WHERE workspace_id = ?",
                        (identifier,),
                    ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError("Unable to update research workspace.") from exc
        return self._row_to_workspace(row) if row is not None else None

    def delete(self, workspace_id: object) -> bool:
        identifier = _clean(workspace_id, limit=128)
        if not identifier:
            return False
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    cursor = connection.execute(
                        "DELETE FROM research_workspaces WHERE workspace_id = ?",
                        (identifier,),
                    )
                    return cursor.rowcount > 0
        except (OSError, sqlite3.Error):
            return False

    @staticmethod
    def _association_table(kind: str) -> tuple[str, str]:
        mapping = {
            "document": ("workspace_documents", "document_id"),
            "note": ("workspace_notes", "note_id"),
            "conversation": ("workspace_conversations", "conversation_id"),
        }
        try:
            return mapping[kind]
        except KeyError as exc:
            raise ValueError(f"Unsupported workspace association kind: {kind}") from exc

    def attach(self, workspace_id: object, *, kind: str, resource_id: object) -> bool:
        identifier = _clean(workspace_id, limit=128)
        member_id = _clean(resource_id, limit=256)
        if not identifier or not member_id:
            return False
        table, column = self._association_table(kind)
        now = _now_iso()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    if connection.execute(
                        "SELECT 1 FROM research_workspaces WHERE workspace_id = ?",
                        (identifier,),
                    ).fetchone() is None:
                        return False
                    cursor = connection.execute(
                        f"INSERT OR IGNORE INTO {table}(workspace_id, {column}, created_at) "
                        "VALUES(?, ?, ?)",
                        (identifier, member_id, now),
                    )
                    connection.execute(
                        "UPDATE research_workspaces SET updated_at = ? WHERE workspace_id = ?",
                        (now, identifier),
                    )
                    return cursor.rowcount > 0
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError("Unable to attach resource to research workspace.") from exc

    def detach(self, workspace_id: object, *, kind: str, resource_id: object) -> bool:
        identifier = _clean(workspace_id, limit=128)
        member_id = _clean(resource_id, limit=256)
        if not identifier or not member_id:
            return False
        table, column = self._association_table(kind)
        now = _now_iso()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    cursor = connection.execute(
                        f"DELETE FROM {table} WHERE workspace_id = ? AND {column} = ?",
                        (identifier, member_id),
                    )
                    if cursor.rowcount > 0:
                        connection.execute(
                            "UPDATE research_workspaces SET updated_at = ? WHERE workspace_id = ?",
                            (now, identifier),
                        )
                    return cursor.rowcount > 0
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError("Unable to detach resource from research workspace.") from exc

    def associations(self, workspace_id: object) -> ResearchWorkspaceAssociations:
        identifier = _clean(workspace_id, limit=128)
        if not identifier:
            return ResearchWorkspaceAssociations()
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                documents = connection.execute(
                    "SELECT document_id FROM workspace_documents "
                    "WHERE workspace_id = ? ORDER BY created_at ASC, document_id ASC",
                    (identifier,),
                ).fetchall()
                notes = connection.execute(
                    "SELECT note_id FROM workspace_notes "
                    "WHERE workspace_id = ? ORDER BY created_at ASC, note_id ASC",
                    (identifier,),
                ).fetchall()
                conversations = connection.execute(
                    "SELECT conversation_id FROM workspace_conversations "
                    "WHERE workspace_id = ? ORDER BY created_at ASC, conversation_id ASC",
                    (identifier,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return ResearchWorkspaceAssociations()
        return ResearchWorkspaceAssociations(
            document_ids=tuple(str(row[0]) for row in documents),
            note_ids=tuple(str(row[0]) for row in notes),
            conversation_ids=tuple(str(row[0]) for row in conversations),
        )

    def workspace_ids_for(self, *, kind: str, resource_id: object) -> tuple[str, ...]:
        member_id = _clean(resource_id, limit=256)
        if not member_id:
            return ()
        table, column = self._association_table(kind)
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                rows = connection.execute(
                    f"SELECT workspace_id FROM {table} WHERE {column} = ? "
                    "ORDER BY created_at DESC, workspace_id ASC",
                    (member_id,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return ()
        return tuple(str(row[0]) for row in rows)


__all__ = [
    "ResearchWorkspace",
    "ResearchWorkspaceAssociations",
    "ResearchWorkspaceStore",
]
