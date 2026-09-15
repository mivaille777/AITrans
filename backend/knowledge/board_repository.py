from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock

from backend.knowledge.board_domain import KnowledgeBoard, KnowledgeBoardNode


class SqliteKnowledgeBoardRepository:
    """Persistence for visual boards inside the existing knowledge workspace database."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path).expanduser().resolve()
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_boards (
                board_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_board_nodes (
                board_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                x REAL NOT NULL DEFAULT 0,
                y REAL NOT NULL DEFAULT 0,
                width REAL NOT NULL DEFAULT 248,
                height REAL NOT NULL DEFAULT 156,
                collapsed INTEGER NOT NULL DEFAULT 0,
                z_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(board_id, item_id),
                FOREIGN KEY(board_id) REFERENCES knowledge_boards(board_id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_board_nodes_item
                ON knowledge_board_nodes(item_id, board_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_board_nodes_board_z
                ON knowledge_board_nodes(board_id, z_index, item_id);
            """
        )

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            self._ensure_schema(connection)

    @staticmethod
    def _board(row: sqlite3.Row) -> KnowledgeBoard:
        return KnowledgeBoard(
            board_id=row["board_id"],
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _node(row: sqlite3.Row) -> KnowledgeBoardNode:
        return KnowledgeBoardNode(
            board_id=row["board_id"],
            item_id=row["item_id"],
            x=row["x"],
            y=row["y"],
            width=row["width"],
            height=row["height"],
            collapsed=bool(row["collapsed"]),
            z_index=row["z_index"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_board(self, board: KnowledgeBoard) -> KnowledgeBoard:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO knowledge_boards(
                    board_id, name, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(board_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                """,
                (
                    board.board_id,
                    board.name,
                    board.description,
                    board.created_at.isoformat(),
                    board.updated_at.isoformat(),
                ),
            )
        stored = self.get_board(board.board_id)
        if stored is None:
            raise RuntimeError("knowledge board was not persisted")
        return stored

    def get_board(self, board_id: str) -> KnowledgeBoard | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_boards WHERE board_id = ?",
                (board_id,),
            ).fetchone()
        return self._board(row) if row is not None else None

    def list_boards(self) -> list[KnowledgeBoard]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_boards ORDER BY updated_at DESC, board_id ASC"
            ).fetchall()
        return [self._board(row) for row in rows]

    def delete_board(self, board_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_boards WHERE board_id = ?",
                (board_id,),
            )
            return cursor.rowcount > 0

    def save_node(self, node: KnowledgeBoardNode) -> KnowledgeBoardNode:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_board_nodes(
                        board_id, item_id, x, y, width, height, collapsed,
                        z_index, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(board_id, item_id) DO UPDATE SET
                        x=excluded.x,
                        y=excluded.y,
                        width=excluded.width,
                        height=excluded.height,
                        collapsed=excluded.collapsed,
                        z_index=excluded.z_index,
                        updated_at=excluded.updated_at
                    """,
                    (
                        node.board_id,
                        node.item_id,
                        node.x,
                        node.y,
                        node.width,
                        node.height,
                        int(node.collapsed),
                        node.z_index,
                        node.created_at.isoformat(),
                        node.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"knowledge board node violates repository constraints: {exc}"
                ) from exc
        stored = self.get_node(node.board_id, node.item_id)
        if stored is None:
            raise RuntimeError("knowledge board node was not persisted")
        return stored

    def get_node(self, board_id: str, item_id: str) -> KnowledgeBoardNode | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_board_nodes
                WHERE board_id = ? AND item_id = ?
                """,
                (board_id, item_id),
            ).fetchone()
        return self._node(row) if row is not None else None

    def list_nodes(self, board_id: str) -> list[KnowledgeBoardNode]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_board_nodes
                WHERE board_id = ?
                ORDER BY z_index ASC, item_id ASC
                """,
                (board_id,),
            ).fetchall()
        return [self._node(row) for row in rows]

    def delete_node(self, board_id: str, item_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                DELETE FROM knowledge_board_nodes
                WHERE board_id = ? AND item_id = ?
                """,
                (board_id, item_id),
            )
            return cursor.rowcount > 0


__all__ = ["SqliteKnowledgeBoardRepository"]
