from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
)


@dataclass(frozen=True, slots=True)
class StoredMessageGrounding:
    knowledge_enabled: bool = False
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_decision: KnowledgeAccessDecision | None = None
    knowledge_retrieved: bool = False
    knowledge_document_count: int = 0
    knowledge_chunk_count: int = 0
    knowledge_fallback_reason: str = ""
    evidence: tuple[AgentEvidenceItem, ...] = ()
    citations: tuple[AgentCitationRef, ...] = ()


def _connect(storage_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(storage_path), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_message_grounding (
            message_id TEXT PRIMARY KEY,
            knowledge_enabled INTEGER NOT NULL DEFAULT 0,
            knowledge_fallback_reason TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            citations_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(message_id)
                REFERENCES messages(message_id)
                ON DELETE CASCADE
        )
        """
    )
    existing_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(conversation_message_grounding)"
        ).fetchall()
    }
    migrations = {
        "knowledge_access_policy": "TEXT NOT NULL DEFAULT 'auto'",
        "knowledge_decision_json": "TEXT NOT NULL DEFAULT ''",
        "knowledge_retrieved": "INTEGER NOT NULL DEFAULT 0",
        "knowledge_document_count": "INTEGER NOT NULL DEFAULT 0",
        "knowledge_chunk_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in migrations.items():
        if column not in existing_columns:
            connection.execute(
                f"ALTER TABLE conversation_message_grounding ADD COLUMN {column} {definition}"
            )


def _contract_json(items: tuple[object, ...] | list[object]) -> str:
    payload = []
    for item in items:
        model_dump = getattr(item, "model_dump", None)
        payload.append(model_dump(mode="json") if callable(model_dump) else item)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _evidence_items(raw: str) -> tuple[AgentEvidenceItem, ...]:
    try:
        payload = json.loads(raw or "[]")
        if not isinstance(payload, list):
            return ()
        return tuple(AgentEvidenceItem.model_validate(item) for item in payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


def _citation_items(raw: str) -> tuple[AgentCitationRef, ...]:
    try:
        payload = json.loads(raw or "[]")
        if not isinstance(payload, list):
            return ()
        return tuple(AgentCitationRef.model_validate(item) for item in payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


def save_message_grounding(
    storage_path: str | Path,
    message_id: str,
    *,
    knowledge_enabled: bool,
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO,
    knowledge_decision: KnowledgeAccessDecision | None = None,
    knowledge_retrieved: bool = False,
    knowledge_document_count: int = 0,
    knowledge_chunk_count: int = 0,
    knowledge_fallback_reason: str = "",
    evidence: tuple[AgentEvidenceItem, ...] | list[AgentEvidenceItem] = (),
    citations: tuple[AgentCitationRef, ...] | list[AgentCitationRef] = (),
) -> None:
    candidate = str(message_id or "").strip()
    if not candidate:
        raise ValueError("message_id must not be empty")
    with closing(_connect(storage_path)) as connection:
        with connection:
            _ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO conversation_message_grounding(
                    message_id,
                    knowledge_enabled,
                    knowledge_access_policy,
                    knowledge_decision_json,
                    knowledge_retrieved,
                    knowledge_document_count,
                    knowledge_chunk_count,
                    knowledge_fallback_reason,
                    evidence_json,
                    citations_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    knowledge_enabled = excluded.knowledge_enabled,
                    knowledge_access_policy = excluded.knowledge_access_policy,
                    knowledge_decision_json = excluded.knowledge_decision_json,
                    knowledge_retrieved = excluded.knowledge_retrieved,
                    knowledge_document_count = excluded.knowledge_document_count,
                    knowledge_chunk_count = excluded.knowledge_chunk_count,
                    knowledge_fallback_reason = excluded.knowledge_fallback_reason,
                    evidence_json = excluded.evidence_json,
                    citations_json = excluded.citations_json
                """,
                (
                    candidate,
                    int(bool(knowledge_enabled)),
                    KnowledgeAccessPolicy(knowledge_access_policy).value,
                    _contract_json([knowledge_decision]) if knowledge_decision is not None else "",
                    int(bool(knowledge_retrieved)),
                    max(0, int(knowledge_document_count or 0)),
                    max(0, int(knowledge_chunk_count or 0)),
                    str(knowledge_fallback_reason or "").strip(),
                    _contract_json(list(evidence)),
                    _contract_json(list(citations)),
                ),
            )


def load_message_grounding(
    storage_path: str | Path,
    message_id: str,
) -> StoredMessageGrounding:
    candidate = str(message_id or "").strip()
    if not candidate:
        return StoredMessageGrounding()
    with closing(_connect(storage_path)) as connection:
        with connection:
            _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT knowledge_enabled, knowledge_access_policy,
                   knowledge_decision_json, knowledge_retrieved,
                   knowledge_document_count, knowledge_chunk_count,
                   knowledge_fallback_reason,
                   evidence_json, citations_json
            FROM conversation_message_grounding
            WHERE message_id = ?
            """,
            (candidate,),
        ).fetchone()
    if row is None:
        return StoredMessageGrounding()
    decision = None
    raw_decision = str(row["knowledge_decision_json"] or "").strip()
    if raw_decision:
        try:
            payload = json.loads(raw_decision)
            if isinstance(payload, list) and payload:
                decision = KnowledgeAccessDecision.model_validate(payload[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            decision = None
    try:
        policy = KnowledgeAccessPolicy(str(row["knowledge_access_policy"] or "auto"))
    except ValueError:
        policy = KnowledgeAccessPolicy.AUTO
    return StoredMessageGrounding(
        knowledge_enabled=bool(row["knowledge_enabled"]),
        knowledge_access_policy=policy,
        knowledge_decision=decision,
        knowledge_retrieved=bool(row["knowledge_retrieved"]),
        knowledge_document_count=max(0, int(row["knowledge_document_count"] or 0)),
        knowledge_chunk_count=max(0, int(row["knowledge_chunk_count"] or 0)),
        knowledge_fallback_reason=str(row["knowledge_fallback_reason"] or ""),
        evidence=_evidence_items(str(row["evidence_json"] or "[]")),
        citations=_citation_items(str(row["citations_json"] or "[]")),
    )


__all__ = [
    "StoredMessageGrounding",
    "load_message_grounding",
    "save_message_grounding",
]
