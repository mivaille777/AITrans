from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from app.infrastructure.paths import writable_config_dir

DEFAULT_AGENT_CHECKPOINT_FILENAME = "agent_checkpoints.sqlite3"


class AgentCheckpointService:
    """Own the process-wide durable LangGraph checkpoint connection.

    AITrans is a single-user desktop application, so a WAL-backed synchronous
    SQLite saver matches the existing local persistence model. Graph state is
    intentionally JSON-compatible and strict msgpack loading prevents a
    compromised checkpoint database from importing arbitrary Python modules.
    """

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else writable_config_dir() / DEFAULT_AGENT_CHECKPOINT_FILENAME
        )
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self.storage_path,
            timeout=5.0,
            check_same_thread=False,
        )
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self.checkpointer = SqliteSaver(
            self._connection,
            serde=JsonPlusSerializer(allowed_msgpack_modules=()),
        )
        self.checkpointer.setup()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True


__all__ = [
    "DEFAULT_AGENT_CHECKPOINT_FILENAME",
    "AgentCheckpointService",
]
