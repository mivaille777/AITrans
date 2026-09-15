from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterable

from app.infrastructure.paths import writable_config_dir
from backend.agent_core.events import AgentEvent
from backend.agent_core.state import AgentState

DEFAULT_AGENT_OBSERVABILITY_FILENAME = "agent_observability.sqlite3"
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredAgentRun:
    run_id: str
    trace_id: str
    session_id: str
    created_at: str
    status: str
    intent: str
    ui_mode: str
    tool_name: str
    provider: str
    model: str
    total_duration_ms: int
    planning_duration_ms: int
    tool_duration_ms: int
    synthesis_duration_ms: int
    retry_count: int
    failure_count: int
    timeout_count: int
    fallback_reason: str
    event_count: int


@dataclass(frozen=True, slots=True)
class StoredAgentEvent:
    """One already-redacted persisted runtime event.

    The event payload is constrained by ``_ALLOWED_EVENT_FIELDS`` before it is
    written to SQLite. Evaluation code can therefore inspect the execution
    trajectory without gaining access to user text, document content, model
    output, tool arguments, or private reasoning.
    """

    sequence: int
    event_type: str
    timestamp: str
    elapsed_ms: int
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class AgentObservabilitySummary:
    sample_size: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    confirmation_required_runs: int
    success_rate: float
    schema_valid_rate: float
    retry_rate: float
    failure_rate: float
    timeout_rate: float
    fallback_rate: float
    average_total_duration_ms: float
    p95_total_duration_ms: int
    average_planning_duration_ms: float
    average_tool_duration_ms: float
    average_synthesis_duration_ms: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_text(value: object) -> str:
    return str(value or "").strip()


def _percentile_95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95 + 0.999999)))
    return ordered[index]


_ALLOWED_EVENT_FIELDS: dict[str, frozenset[str]] = {
    "agent_start": frozenset({"budget_ms"}),
    "context_ready": frozenset({"source_kind"}),
    "plan_ready": frozenset(
        {
            "action",
            "tool_name",
            "mode",
            "route_kind",
            "route_source",
            "request_id",
            "duration_ms",
            "provider",
            "model",
            "prompt_id",
        }
    ),
    "react_started": frozenset(
        {"max_iterations", "max_tool_calls", "max_knowledge_searches", "request_id"}
    ),
    "decision_ready": frozenset(
        {
            "iteration",
            "kind",
            "tool_name",
            "argument_keys",
            "action_fingerprint",
            "provider",
            "model",
            "prompt_id",
        }
    ),
    "tool_call": frozenset(
        {"name", "effect", "requires_confirmation", "request_id"}
    ),
    "retry": frozenset({"tool_name", "attempt", "max_attempts", "request_id"}),
    "tool_result": frozenset(
        {
            "tool_name",
            "effect",
            "provider",
            "model",
            "request_id",
            "duration_ms",
        }
    ),
    "observation_ready": frozenset(
        {
            "observation_id",
            "iteration",
            "tool_name",
            "success",
            "summary_chars",
            "evidence_count",
            "citation_count",
            "knowledge_search_count",
            "query_fingerprint",
            "retrieval_strategy",
            "result_count",
            "novel_evidence_count",
            "retrieval_fallback",
            "gate_action",
            "gate_quality_score",
        }
    ),
    "evidence_gate_evaluated": frozenset(
        {
            "iteration",
            "action",
            "coverage_score",
            "diversity_score",
            "novelty_score",
            "quality_score",
            "evidence_count",
            "unique_source_count",
            "unique_location_count",
            "novel_evidence_count",
            "search_count",
            "remaining_searches",
            "retrieval_fallback",
            "reason_codes",
        }
    ),
    "react_limit_reached": frozenset(
        {"iteration", "tool_call_count", "knowledge_search_count", "reason"}
    ),
    "rag_query_started": frozenset({"query_id", "retrieval_strategy"}),
    "rag_query_rewritten": frozenset(
        {"query_id", "rewritten", "subquery_count"}
    ),
    "rag_dense_completed": frozenset(
        {"query_id", "dense_count", "embedding_ms", "dense_search_ms"}
    ),
    "rag_sparse_completed": frozenset(
        {"query_id", "sparse_count", "sparse_search_ms"}
    ),
    "rag_fusion_completed": frozenset(
        {"query_id", "fusion_count", "fusion_ms"}
    ),
    "rag_rerank_completed": frozenset(
        {"query_id", "final_count", "rerank_ms"}
    ),
    "rag_evidence_selected": frozenset(
        {"query_id", "final_count", "total_rag_ms", "evidence"}
    ),
    "rag_fallback": frozenset({"query_id", "fallback_reason"}),
    "grounding_verification_evaluated": frozenset(
        {
            "passed",
            "fallback_applied",
            "claim_count",
            "cited_claim_count",
            "supported_claim_count",
            "unsupported_claim_count",
            "invalid_citation_count",
            "citation_coverage",
            "support_rate",
            "reason_codes",
            "request_id",
        }
    ),
    "synthesis_ready": frozenset(
        {
            "provider",
            "model",
            "prompt_id",
            "request_id",
            "duration_ms",
            "source",
            "grounded",
        }
    ),
    "failure": frozenset({"code", "stage", "fallback_reason"}),
    "cancelled": frozenset({"code", "fallback_reason"}),
    "agent_end": frozenset(
        {"intent", "status", "ui_mode", "total_duration_ms"}
    ),
}


def _redacted_payload(event: AgentEvent) -> dict[str, object]:
    allowed = _ALLOWED_EVENT_FIELDS.get(event.event_type.value, frozenset())
    return {key: event.payload[key] for key in allowed if key in event.payload}


class AgentTraceStoreService:
    """Privacy-preserving local persistence for Agent runtime telemetry.

    Raw reading text, surrounding context, user messages and model output are
    intentionally excluded. The store keeps only correlation identifiers,
    lifecycle metadata and bounded diagnostic metrics required for reliability
    analysis and regression evaluation.
    """

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else writable_config_dir() / DEFAULT_AGENT_OBSERVABILITY_FILENAME
        )
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
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                ui_mode TEXT NOT NULL DEFAULT 'assistant',
                tool_name TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                total_duration_ms INTEGER NOT NULL DEFAULT 0,
                planning_duration_ms INTEGER NOT NULL DEFAULT 0,
                tool_duration_ms INTEGER NOT NULL DEFAULT 0,
                synthesis_duration_ms INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                timeout_count INTEGER NOT NULL DEFAULT 0,
                fallback_reason TEXT NOT NULL DEFAULT '',
                event_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at
                ON agent_runs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_runs_trace_id
                ON agent_runs(trace_id, created_at ASC);

            CREATE TABLE IF NOT EXISTS agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                UNIQUE(run_id, sequence)
            );

            CREATE INDEX IF NOT EXISTS idx_agent_events_run_sequence
                ON agent_events(run_id, sequence ASC);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)

    @staticmethod
    def _derive_run(state: AgentState, events: tuple[AgentEvent, ...]) -> StoredAgentRun:
        event_by_type: dict[str, list[AgentEvent]] = {}
        for event in events:
            event_by_type.setdefault(event.event_type.value, []).append(event)

        end_event = event_by_type.get("agent_end", [None])[-1]
        end_payload = end_event.payload if end_event is not None else {}
        plan_event = event_by_type.get("plan_ready", [None])[-1]
        plan_payload = plan_event.payload if plan_event is not None else {}
        tool_result_event = event_by_type.get("tool_result", [None])[-1]
        tool_result_payload = tool_result_event.payload if tool_result_event is not None else {}
        synthesis_event = event_by_type.get("synthesis_ready", [None])[-1]
        synthesis_payload = synthesis_event.payload if synthesis_event is not None else {}
        failure_event = event_by_type.get("failure", [None])[-1]
        failure_payload = failure_event.payload if failure_event is not None else {}

        tool_name = _safe_text(plan_payload.get("tool_name"))
        if not tool_name and state.tool_calls:
            tool_name = _safe_text(state.tool_calls[-1].get("name"))

        status = _safe_text(end_payload.get("status"))
        if not status:
            status = _safe_text(state.response.get("status")) or "unknown"

        timeout_count = sum(
            1
            for event in event_by_type.get("failure", [])
            if _safe_text(event.payload.get("code"))
            in {"AgentToolTimeoutError", "AgentBudgetExceededError"}
        )

        created_at = events[0].timestamp if events else _now_iso()
        total_duration_ms = _safe_int(end_payload.get("total_duration_ms"))
        if not total_duration_ms and events:
            total_duration_ms = max(event.elapsed_ms for event in events)

        return StoredAgentRun(
            run_id=state.run_id,
            trace_id=state.trace_id,
            session_id=_safe_text(state.session_id),
            created_at=created_at,
            status=status,
            intent=_safe_text(end_payload.get("intent")) or _safe_text(state.intent),
            ui_mode=_safe_text(end_payload.get("ui_mode")) or state.ui_mode,
            tool_name=tool_name,
            provider=_safe_text(tool_result_payload.get("provider"))
            or _safe_text(synthesis_payload.get("provider"))
            or _safe_text(state.response.get("provider")),
            model=_safe_text(tool_result_payload.get("model"))
            or _safe_text(synthesis_payload.get("model"))
            or _safe_text(state.response.get("model")),
            total_duration_ms=total_duration_ms,
            planning_duration_ms=_safe_int(plan_payload.get("duration_ms")),
            tool_duration_ms=_safe_int(tool_result_payload.get("duration_ms")),
            synthesis_duration_ms=_safe_int(synthesis_payload.get("duration_ms")),
            retry_count=len(event_by_type.get("retry", [])),
            failure_count=len(event_by_type.get("failure", [])),
            timeout_count=timeout_count,
            fallback_reason=_safe_text(failure_payload.get("fallback_reason")),
            event_count=len(events),
        )

    def record(self, state: AgentState, events: Iterable[AgentEvent]) -> StoredAgentRun:
        frozen_events = tuple(events)
        run = self._derive_run(state, frozen_events)
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO agent_runs(
                            run_id, trace_id, session_id, created_at, status, intent,
                            ui_mode, tool_name, provider, model, total_duration_ms,
                            planning_duration_ms, tool_duration_ms,
                            synthesis_duration_ms, retry_count, failure_count,
                            timeout_count, fallback_reason, event_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run.run_id,
                            run.trace_id,
                            run.session_id,
                            run.created_at,
                            run.status,
                            run.intent,
                            run.ui_mode,
                            run.tool_name,
                            run.provider,
                            run.model,
                            run.total_duration_ms,
                            run.planning_duration_ms,
                            run.tool_duration_ms,
                            run.synthesis_duration_ms,
                            run.retry_count,
                            run.failure_count,
                            run.timeout_count,
                            run.fallback_reason,
                            run.event_count,
                        ),
                    )
                    connection.execute("DELETE FROM agent_events WHERE run_id = ?", (run.run_id,))
                    connection.executemany(
                        """
                        INSERT INTO agent_events(
                            run_id, sequence, event_type, timestamp, elapsed_ms, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                run.run_id,
                                sequence,
                                event.event_type.value,
                                event.timestamp,
                                event.elapsed_ms,
                                json.dumps(_redacted_payload(event), ensure_ascii=False),
                            )
                            for sequence, event in enumerate(frozen_events)
                        ],
                    )
        return run

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> StoredAgentRun:
        return StoredAgentRun(
            run_id=str(row["run_id"]),
            trace_id=str(row["trace_id"]),
            session_id=str(row["session_id"]),
            created_at=str(row["created_at"]),
            status=str(row["status"]),
            intent=str(row["intent"]),
            ui_mode=str(row["ui_mode"]),
            tool_name=str(row["tool_name"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            total_duration_ms=int(row["total_duration_ms"]),
            planning_duration_ms=int(row["planning_duration_ms"]),
            tool_duration_ms=int(row["tool_duration_ms"]),
            synthesis_duration_ms=int(row["synthesis_duration_ms"]),
            retry_count=int(row["retry_count"]),
            failure_count=int(row["failure_count"]),
            timeout_count=int(row["timeout_count"]),
            fallback_reason=str(row["fallback_reason"]),
            event_count=int(row["event_count"]),
        )

    def list_recent(self, *, limit: int = 30) -> tuple[StoredAgentRun, ...]:
        bounded = max(1, min(int(limit), 500))
        with self._lock:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                rows = connection.execute(
                    "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
                return tuple(self._run_from_row(row) for row in rows)

    def get_run(self, run_id: str) -> StoredAgentRun | None:
        candidate = str(run_id or "").strip()
        if not candidate:
            return None
        with self._lock:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    "SELECT * FROM agent_runs WHERE run_id = ?", (candidate,)
                ).fetchone()
                return self._run_from_row(row) if row is not None else None

    def summary(self, *, limit: int = 100) -> AgentObservabilitySummary:
        runs = list(self.list_recent(limit=limit))
        sample_size = len(runs)
        completed = sum(run.status == "completed" for run in runs)
        failed = sum(run.status == "failed" for run in runs)
        cancelled = sum(run.status == "cancelled" for run in runs)
        confirmations = sum(run.status == "confirmation_required" for run in runs)
        schema_valid = sum(bool(run.intent) for run in runs)
        retries = sum(run.retry_count > 0 for run in runs)
        timeouts = sum(run.timeout_count > 0 for run in runs)
        fallbacks = sum(bool(run.fallback_reason) for run in runs)
        total_durations = [run.total_duration_ms for run in runs]

        def average(values: list[int]) -> float:
            return round(sum(values) / len(values), 2) if values else 0.0

        denominator = sample_size or 1
        return AgentObservabilitySummary(
            sample_size=sample_size,
            completed_runs=completed,
            failed_runs=failed,
            cancelled_runs=cancelled,
            confirmation_required_runs=confirmations,
            success_rate=round(completed / denominator, 4) if sample_size else 0.0,
            schema_valid_rate=round(schema_valid / denominator, 4) if sample_size else 0.0,
            retry_rate=round(retries / denominator, 4) if sample_size else 0.0,
            failure_rate=round(failed / denominator, 4) if sample_size else 0.0,
            timeout_rate=round(timeouts / denominator, 4) if sample_size else 0.0,
            fallback_rate=round(fallbacks / denominator, 4) if sample_size else 0.0,
            average_total_duration_ms=average(total_durations),
            p95_total_duration_ms=_percentile_95(total_durations),
            average_planning_duration_ms=average(
                [run.planning_duration_ms for run in runs if run.planning_duration_ms > 0]
            ),
            average_tool_duration_ms=average(
                [run.tool_duration_ms for run in runs if run.tool_duration_ms > 0]
            ),
            average_synthesis_duration_ms=average(
                [run.synthesis_duration_ms for run in runs if run.synthesis_duration_ms > 0]
            ),
        )

    def list_events(self, run_id: str) -> tuple[StoredAgentEvent, ...]:
        """Return the redacted persisted event sequence for one run."""

        candidate = str(run_id or "").strip()
        if not candidate:
            return ()
        with self._lock:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                rows = connection.execute(
                    """
                    SELECT sequence, event_type, timestamp, elapsed_ms, payload_json
                    FROM agent_events
                    WHERE run_id = ?
                    ORDER BY sequence ASC
                    """,
                    (candidate,),
                ).fetchall()
        return tuple(
            StoredAgentEvent(
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                timestamp=str(row["timestamp"]),
                elapsed_ms=int(row["elapsed_ms"]),
                payload=json.loads(str(row["payload_json"])),
            )
            for row in rows
        )

    def event_payloads(self, run_id: str) -> tuple[dict[str, object], ...]:
        """Testing/debug helper returning only already-redacted persisted payloads."""
        return tuple(event.payload for event in self.list_events(run_id))


__all__ = [
    "AgentTraceStoreService",
    "StoredAgentRun",
    "StoredAgentEvent",
    "AgentObservabilitySummary",
]
