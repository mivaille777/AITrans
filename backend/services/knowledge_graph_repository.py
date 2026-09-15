from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class KnowledgeGraphRepository:
    """Persistent storage for Knowledge Canvas graph state.

    The repository intentionally stores graph structure separately from RAG
    indexes. Documents, embeddings and graph relations can evolve
    independently.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or "data/knowledge_graph.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_canvas_graph (
                    graph_id INTEGER PRIMARY KEY CHECK (graph_id = 1),
                    payload TEXT NOT NULL
                )
                """
            )

    def get_graph(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM knowledge_canvas_graph WHERE graph_id = 1"
            ).fetchone()
        if row is None:
            return {"nodes": [], "edges": []}
        return json.loads(row[0])

    def save_graph(self, graph: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(graph, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_canvas_graph(graph_id, payload)
                VALUES(1, ?)
                ON CONFLICT(graph_id) DO UPDATE SET payload=excluded.payload
                """,
                (payload,),
            )
        return graph
