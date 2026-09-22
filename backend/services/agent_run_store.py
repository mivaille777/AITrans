from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.infrastructure.paths import writable_config_dir
from backend.agent_core.events import AgentEvent, AgentEventType
from backend.models.agent_run import (
    AgentRunRecord,
    AgentRunStatus,
    AgentStepRecord,
    AgentToolCallRecord,
    AgentToolCallStatus,
    AgentWorkerLeaseRecord,
    transition_run,
)
from backend.models.agent_tasks import AgentTaskRecord

DEFAULT_AGENT_RUNTIME_FILENAME = "agent_runtime.sqlite3"
AGENT_RUNTIME_SCHEMA_VERSION = 4


class AgentRunStoreError(RuntimeError):
    pass


class AgentRunStoreConflictError(AgentRunStoreError):
    pass


class AgentRunStoreNotFoundError(AgentRunStoreError):
    pass


def _as_utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=UTC)
    return resolved.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    return datetime.fromisoformat(text) if text else None


class AgentRunStore:
    """Authoritative SQLite lifecycle store for Agent Runtime v1."""

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else writable_config_dir() / DEFAULT_AGENT_RUNTIME_FILENAME
        )
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        with closing(self._connect()) as connection:
            self._ensure_schema(connection)

    def _ensure_open(self) -> None:
        if self._closed:
            raise AgentRunStoreError("agent run store is closed")

    def _connect(self) -> sqlite3.Connection:
        self._ensure_open()
        connection = sqlite3.connect(
            self.storage_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_runtime_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_tasks (
                task_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                workspace_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                runtime_profile TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                graph_version TEXT NOT NULL DEFAULT '',
                state_schema_version INTEGER NOT NULL DEFAULT 0,
                checkpoint_id TEXT NOT NULL DEFAULT '',
                budget_used_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY(task_id) REFERENCES agent_tasks(task_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_agent_runs_task_created
                ON agent_runs(task_id, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_agent_runs_status_created
                ON agent_runs(status, created_at ASC);

            CREATE TABLE IF NOT EXISTS agent_steps (
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                PRIMARY KEY(run_id, step_id),
                FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                tool_call_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                record_json TEXT NOT NULL,
                result_json TEXT,
                FOREIGN KEY(run_id, step_id)
                    REFERENCES agent_steps(run_id, step_id) ON DELETE CASCADE,
                UNIQUE(run_id, idempotency_key)
            );

            CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_run_step
                ON agent_tool_calls(run_id, step_id);

            CREATE TABLE IF NOT EXISTS agent_runtime_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                task_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                step_id TEXT NOT NULL DEFAULT '',
                tool_call_id TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                UNIQUE(run_id, sequence)
            );

            CREATE INDEX IF NOT EXISTS idx_agent_runtime_events_run_sequence
                ON agent_runtime_events(run_id, sequence ASC);

            CREATE TABLE IF NOT EXISTS agent_worker_leases (
                run_id TEXT PRIMARY KEY,
                lease_owner TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
            );
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        try:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(agent_runs)")
            }
            if "request_json" not in columns:
                connection.execute(
                    "ALTER TABLE agent_runs ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "result_json" not in columns:
                connection.execute("ALTER TABLE agent_runs ADD COLUMN result_json TEXT")
            for name, declaration in (
                ("graph_version", "TEXT NOT NULL DEFAULT ''"),
                ("state_schema_version", "INTEGER NOT NULL DEFAULT 0"),
                ("checkpoint_id", "TEXT NOT NULL DEFAULT ''"),
                ("budget_used_ms", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {declaration}")
            tool_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(agent_tool_calls)")
            }
            if "result_json" not in tool_columns:
                connection.execute("ALTER TABLE agent_tool_calls ADD COLUMN result_json TEXT")
            connection.execute(
                """
                INSERT INTO agent_runtime_state(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(AGENT_RUNTIME_SCHEMA_VERSION),),
            )
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _insert_task(connection: sqlite3.Connection, task: AgentTaskRecord) -> None:
        connection.execute(
            """
            INSERT INTO agent_tasks(task_id, goal, workspace_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task.task_id, task.goal, task.workspace_id, _iso(task.created_at)),
        )

    @staticmethod
    def _insert_run(
        connection: sqlite3.Connection,
        run: AgentRunRecord,
        request_payload: dict[str, object] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO agent_runs(
                run_id, task_id, trace_id, runtime_profile, request_json, status,
                created_at, updated_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.task_id,
                run.trace_id,
                run.runtime_profile.value,
                json.dumps(request_payload or {}, ensure_ascii=False, sort_keys=True),
                run.status.value,
                _iso(run.created_at),
                _iso(run.updated_at),
                _iso(run.started_at),
                _iso(run.finished_at),
            ),
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> AgentTaskRecord:
        return AgentTaskRecord(
            task_id=str(row["task_id"]),
            goal=str(row["goal"]),
            workspace_id=str(row["workspace_id"]),
            created_at=_parse_datetime(row["created_at"]),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> AgentRunRecord:
        return AgentRunRecord(
            task_id=str(row["task_id"]),
            run_id=str(row["run_id"]),
            trace_id=str(row["trace_id"]),
            runtime_profile=str(row["runtime_profile"]),
            status=str(row["status"]),
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
            started_at=_parse_datetime(row["started_at"]),
            finished_at=_parse_datetime(row["finished_at"]),
            graph_version=str(row["graph_version"]),
            state_schema_version=int(row["state_schema_version"]),
            checkpoint_id=str(row["checkpoint_id"]),
            budget_used_ms=int(row["budget_used_ms"]),
        )

    def create_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        try:
            with self._write_transaction() as connection:
                self._insert_task(connection, task)
        except sqlite3.IntegrityError as exc:
            raise AgentRunStoreConflictError(f"task already exists: {task.task_id}") from exc
        return task.model_copy(deep=True)

    def create_run(
        self, run: AgentRunRecord, *, request_payload: dict[str, object] | None = None
    ) -> AgentRunRecord:
        try:
            with self._write_transaction() as connection:
                self._insert_run(connection, run, request_payload)
        except sqlite3.IntegrityError as exc:
            raise AgentRunStoreConflictError(
                f"run cannot be created: {run.run_id}"
            ) from exc
        return run.model_copy(deep=True)

    def create_task_and_run(
        self,
        task: AgentTaskRecord,
        run: AgentRunRecord,
        *,
        request_payload: dict[str, object] | None = None,
    ) -> tuple[AgentTaskRecord, AgentRunRecord]:
        if run.task_id != task.task_id:
            raise ValueError("run task_id must match the owning task")
        try:
            with self._write_transaction() as connection:
                self._insert_task(connection, task)
                self._insert_run(connection, run, request_payload)
        except sqlite3.IntegrityError as exc:
            raise AgentRunStoreConflictError(
                f"task or run already exists: {task.task_id}/{run.run_id}"
            ) from exc
        return task.model_copy(deep=True), run.model_copy(deep=True)

    def get_task(self, task_id: str) -> AgentTaskRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._task_from_row(row) if row is not None else None

    def get_run(self, run_id: str) -> AgentRunRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def get_run_request(self, run_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT request_json FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(str(row["request_json"])) if row is not None else None

    def get_run_result(self, run_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT result_json FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None or row["result_json"] is None:
            return None
        return json.loads(str(row["result_json"]))

    def transition_run(
        self,
        run_id: str,
        *,
        expected_status: AgentRunStatus,
        target_status: AgentRunStatus,
    ) -> AgentRunRecord:
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise AgentRunStoreNotFoundError(f"run not found: {run_id}")
            current = self._run_from_row(row)
            if current.status is not expected_status:
                raise AgentRunStoreConflictError(
                    f"run {run_id} status is {current.status.value}, "
                    f"expected {expected_status.value}"
                )
            updated = transition_run(current, target_status)
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, updated_at = ?, started_at = ?, finished_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    _iso(updated.updated_at),
                    _iso(updated.started_at),
                    _iso(updated.finished_at),
                    run_id,
                    expected_status.value,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRunStoreConflictError(
                    f"run {run_id} changed during transition"
                )
        return updated

    def claim_run(
        self,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
        now: datetime | None = None,
    ) -> AgentRunRecord | None:
        claim = self.claim_next_run(
            lease_owner=lease_owner, lease_seconds=lease_seconds, now=now
        )
        return claim[0] if claim is not None else None

    def claim_next_run(
        self,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
        now: datetime | None = None,
    ) -> tuple[AgentRunRecord, bool] | None:
        owner = str(lease_owner or "").strip()
        if not owner:
            raise ValueError("lease_owner is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claimed_at = _as_utc(now)
        with self._write_transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM agent_runs
                WHERE status IN (?, ?)
                ORDER BY CASE status WHEN ? THEN 0 ELSE 1 END,
                         created_at ASC, run_id ASC
                LIMIT 1
                """,
                (
                    AgentRunStatus.RECOVERING.value,
                    AgentRunStatus.QUEUED.value,
                    AgentRunStatus.RECOVERING.value,
                ),
            ).fetchone()
            if row is None:
                return None
            current = self._run_from_row(row)
            recovering = current.status is AgentRunStatus.RECOVERING
            updated = transition_run(current, AgentRunStatus.RUNNING).model_copy(
                update={"started_at": current.started_at or claimed_at, "updated_at": claimed_at}
            )
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, updated_at = ?, started_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    _iso(updated.updated_at),
                    _iso(updated.started_at),
                    updated.run_id,
                    current.status.value,
                ),
            )
            if cursor.rowcount != 1:
                return None
            connection.execute(
                """
                INSERT INTO agent_worker_leases(
                    run_id, lease_owner, lease_expires_at, heartbeat_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    updated.run_id,
                    owner,
                    _iso(claimed_at + timedelta(seconds=lease_seconds)),
                    _iso(claimed_at),
                ),
            )
        return updated, recovering

    def heartbeat_lease(
        self,
        run_id: str,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
        budget_used_ms: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        heartbeat_at = _as_utc(now)
        with self._write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_worker_leases
                SET heartbeat_at = ?, lease_expires_at = ?
                WHERE run_id = ? AND lease_owner = ? AND lease_expires_at > ?
                  AND EXISTS (
                      SELECT 1 FROM agent_runs
                      WHERE run_id = ? AND status IN (?, ?)
                  )
                """,
                (
                    _iso(heartbeat_at),
                    _iso(heartbeat_at + timedelta(seconds=lease_seconds)),
                    run_id,
                    lease_owner,
                    _iso(heartbeat_at),
                    run_id,
                    AgentRunStatus.RUNNING.value,
                    AgentRunStatus.PAUSE_REQUESTED.value,
                ),
            )
            if cursor.rowcount == 1 and budget_used_ms is not None:
                connection.execute(
                    """
                    UPDATE agent_runs SET budget_used_ms = MAX(budget_used_ms, ?)
                    WHERE run_id = ?
                    """,
                    (budget_used_ms, run_id),
                )
            return cursor.rowcount == 1

    def recover_expired_runs(self, *, now: datetime | None = None) -> tuple[str, ...]:
        expired_at = _as_utc(now)
        with self._write_transaction() as connection:
            rows = connection.execute(
                """
                SELECT r.run_id, r.status FROM agent_runs AS r
                JOIN agent_worker_leases AS l ON l.run_id = r.run_id
                WHERE r.status IN (?, ?) AND l.lease_expires_at <= ?
                ORDER BY r.created_at, r.run_id
                """,
                (
                    AgentRunStatus.RUNNING.value,
                    AgentRunStatus.PAUSE_REQUESTED.value,
                    _iso(expired_at),
                ),
            ).fetchall()
            run_ids = tuple(str(row["run_id"]) for row in rows)
            for row in rows:
                run_id = str(row["run_id"])
                previous_status = AgentRunStatus(str(row["status"]))
                target = (
                    AgentRunStatus.PAUSED
                    if previous_status is AgentRunStatus.PAUSE_REQUESTED
                    else AgentRunStatus.RECOVERING
                )
                connection.execute(
                    """
                    UPDATE agent_runs SET status = ?, updated_at = ?
                    WHERE run_id = ? AND status = ?
                    """,
                    (
                        target.value,
                        _iso(expired_at),
                        run_id,
                        previous_status.value,
                    ),
                )
                connection.execute(
                    "DELETE FROM agent_worker_leases WHERE run_id = ?", (run_id,)
                )
        return run_ids

    def pause_run(self, run_id: str) -> AgentRunRecord:
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise AgentRunStoreNotFoundError(f"run not found: {run_id}")
            current = self._run_from_row(row)
            if current.status in (AgentRunStatus.PAUSED, AgentRunStatus.PAUSE_REQUESTED):
                return current
            if current.status is not AgentRunStatus.RUNNING:
                raise AgentRunStoreConflictError(
                    f"run {run_id} cannot pause from {current.status.value}"
                )
            updated = transition_run(current, AgentRunStatus.PAUSE_REQUESTED)
            connection.execute(
                """
                UPDATE agent_runs SET status = ?, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    _iso(updated.updated_at),
                    run_id,
                    current.status.value,
                ),
            )
        return updated

    def resume_run(self, run_id: str) -> AgentRunRecord:
        return self.transition_run(
            run_id,
            expected_status=AgentRunStatus.PAUSED,
            target_status=AgentRunStatus.RECOVERING,
        )


    def confirm_waiting_run(self, run_id: str, *, tool_name: str) -> AgentRunRecord:
        tool = str(tool_name or "").strip()
        if not tool:
            raise ValueError("tool_name is required")
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise AgentRunStoreNotFoundError(f"run not found: {run_id}")
            current = self._run_from_row(row)
            if current.status is not AgentRunStatus.WAITING:
                raise AgentRunStoreConflictError(
                    f"run {run_id} cannot confirm from {current.status.value}"
                )
            request_row = connection.execute(
                "SELECT request_json FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            request_payload = json.loads(str(request_row["request_json"]))
            request_payload["confirmed_write_tools"] = [tool]
            updated = transition_run(current, AgentRunStatus.RECOVERING)
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, updated_at = ?, request_json = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    _iso(updated.updated_at),
                    json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
                    run_id,
                    current.status.value,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRunStoreConflictError(
                    f"run {run_id} changed during confirmation"
                )
        return updated

    def update_checkpoint_metadata(
        self,
        run_id: str,
        *,
        lease_owner: str,
        graph_version: str,
        state_schema_version: int,
        checkpoint_id: str,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        checked_at = _as_utc(now)
        if not graph_version or not checkpoint_id or state_schema_version < 1:
            raise ValueError("complete checkpoint metadata is required")
        with self._write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET graph_version = ?, state_schema_version = ?, checkpoint_id = ?
                WHERE run_id = ? AND status IN (?, ?)
                  AND EXISTS (
                    SELECT 1 FROM agent_worker_leases
                    WHERE run_id = ? AND lease_owner = ? AND lease_expires_at > ?
                  )
                """,
                (
                    graph_version,
                    state_schema_version,
                    checkpoint_id,
                    run_id,
                    AgentRunStatus.RUNNING.value,
                    AgentRunStatus.PAUSE_REQUESTED.value,
                    run_id,
                    lease_owner,
                    _iso(checked_at),
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRunStoreConflictError(
                    f"run {run_id} checkpoint cannot be updated by {lease_owner}"
                )
        return self.get_run(run_id)

    def prepare_recovery_tool_calls(
        self, run_id: str, *, lease_owner: str
    ) -> tuple[str, ...]:
        """Fence uncertain writes; reset interrupted read/compute calls for retry."""

        blocked: list[str] = []
        with self._write_transaction() as connection:
            active = connection.execute(
                """
                SELECT 1 FROM agent_worker_leases AS l
                JOIN agent_runs AS r ON r.run_id = l.run_id
                WHERE l.run_id = ? AND l.lease_owner = ?
                  AND l.lease_expires_at > ? AND r.status = ?
                """,
                (
                    run_id,
                    lease_owner,
                    _iso(datetime.now(UTC)),
                    AgentRunStatus.RUNNING.value,
                ),
            ).fetchone()
            if active is None:
                raise AgentRunStoreConflictError(
                    f"run {run_id} recovery is not owned by {lease_owner}"
                )
            rows = connection.execute(
                """
                SELECT tool_call_id, record_json FROM agent_tool_calls
                WHERE run_id = ? AND status = ?
                """,
                (run_id, AgentToolCallStatus.RUNNING.value),
            ).fetchall()
            for row in rows:
                call = AgentToolCallRecord.model_validate_json(str(row["record_json"]))
                if call.effect == "write":
                    status = AgentToolCallStatus.BLOCKED_RECOVERY
                    blocked.append(call.tool_call_id)
                else:
                    status = AgentToolCallStatus.PENDING
                updated = call.model_copy(update={"status": status})
                connection.execute(
                    """
                    UPDATE agent_tool_calls SET status = ?, record_json = ?
                    WHERE tool_call_id = ? AND run_id = ? AND status = ?
                    """,
                    (
                        status.value,
                        updated.model_dump_json(),
                        call.tool_call_id,
                        run_id,
                        AgentToolCallStatus.RUNNING.value,
                    ),
                )
        return tuple(blocked)

    def cancel_run(self, run_id: str) -> AgentRunRecord:
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise AgentRunStoreNotFoundError(f"run not found: {run_id}")
            current = self._run_from_row(row)
            if current.status in (
                AgentRunStatus.COMPLETED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            ):
                return current
            updated = transition_run(current, AgentRunStatus.CANCELLED)
            connection.execute(
                """
                UPDATE agent_runs SET status = ?, updated_at = ?, finished_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    _iso(updated.updated_at),
                    _iso(updated.finished_at),
                    run_id,
                    current.status.value,
                ),
            )
            connection.execute(
                "DELETE FROM agent_worker_leases WHERE run_id = ?", (run_id,)
            )
        return updated

    def finish_owned_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        target_status: AgentRunStatus,
        result_payload: dict[str, object] | None = None,
        budget_used_ms: int | None = None,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        if target_status not in (
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.WAITING,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.PAUSED,
        ):
            raise ValueError("unsupported owned run target status")
        finished_at = _as_utc(now)
        with self._write_transaction() as connection:
            row = connection.execute(
                """
                SELECT r.* FROM agent_runs AS r
                JOIN agent_worker_leases AS l ON l.run_id = r.run_id
                WHERE r.run_id = ? AND r.status IN (?, ?) AND l.lease_owner = ?
                  AND l.lease_expires_at > ?
                """,
                (
                    run_id,
                    AgentRunStatus.RUNNING.value,
                    AgentRunStatus.PAUSE_REQUESTED.value,
                    lease_owner,
                    _iso(finished_at),
                ),
            ).fetchone()
            if row is None:
                raise AgentRunStoreConflictError(
                    f"run {run_id} is not running under lease {lease_owner}"
                )
            current = self._run_from_row(row)
            updated = transition_run(current, target_status).model_copy(
                update={
                    "updated_at": finished_at,
                    "finished_at": (
                        finished_at
                        if target_status not in (AgentRunStatus.WAITING, AgentRunStatus.PAUSED)
                        else None
                    ),
                    "budget_used_ms": max(
                        current.budget_used_ms,
                        budget_used_ms if budget_used_ms is not None else 0,
                    ),
                }
            )
            connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, updated_at = ?, finished_at = ?, result_json = ?,
                    budget_used_ms = MAX(budget_used_ms, ?)
                WHERE run_id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    _iso(updated.updated_at),
                    _iso(updated.finished_at),
                    (
                        json.dumps(result_payload, ensure_ascii=False, sort_keys=True)
                        if result_payload is not None
                        else None
                    ),
                    budget_used_ms if budget_used_ms is not None else current.budget_used_ms,
                    run_id,
                    current.status.value,
                ),
            )
            connection.execute(
                "DELETE FROM agent_worker_leases WHERE run_id = ?", (run_id,)
            )
        return updated

    def get_lease(self, run_id: str) -> AgentWorkerLeaseRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM agent_worker_leases WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return AgentWorkerLeaseRecord(
            run_id=str(row["run_id"]),
            lease_owner=str(row["lease_owner"]),
            lease_expires_at=_parse_datetime(row["lease_expires_at"]),
            heartbeat_at=_parse_datetime(row["heartbeat_at"]),
        )

    def save_step(self, step: AgentStepRecord) -> AgentStepRecord:
        payload = step.model_dump(mode="json", exclude={"step_id"})
        try:
            with self._write_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_steps(run_id, step_id, status, state_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(run_id, step_id) DO UPDATE SET
                        status = excluded.status,
                        state_json = excluded.state_json
                    """,
                    (
                        step.run_id,
                        step.step_id,
                        step.status.value,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise AgentRunStoreConflictError(
                f"step cannot be saved: {step.run_id}/{step.step_id}"
            ) from exc
        return step.model_copy(deep=True)

    def get_step(self, run_id: str, step_id: str) -> AgentStepRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT state_json FROM agent_steps
                WHERE run_id = ? AND step_id = ?
                """,
                (run_id, step_id),
            ).fetchone()
        if row is None:
            return None
        return AgentStepRecord.model_validate_json(str(row["state_json"]))

    def save_tool_call(self, call: AgentToolCallRecord) -> AgentToolCallRecord:
        payload = call.model_dump(mode="json")
        try:
            with self._write_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_tool_calls(
                        tool_call_id, run_id, step_id, status,
                        idempotency_key, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tool_call_id) DO UPDATE SET
                        status = excluded.status,
                        record_json = excluded.record_json
                    """,
                    (
                        call.tool_call_id,
                        call.run_id,
                        call.step_id,
                        call.status.value,
                        call.idempotency_key,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise AgentRunStoreConflictError(
                f"tool call cannot be saved: {call.tool_call_id}"
            ) from exc
        return call.model_copy(deep=True)

    def get_tool_call(self, tool_call_id: str) -> AgentToolCallRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT record_json FROM agent_tool_calls WHERE tool_call_id = ?",
                (tool_call_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentToolCallRecord.model_validate_json(str(row["record_json"]))

    def claim_tool_call(
        self, call: AgentToolCallRecord
    ) -> tuple[AgentToolCallRecord, bool, dict | None]:
        """Atomically claim one execution key. Existing writes are never reclaimed."""
        with self._write_transaction() as connection:
            step = AgentStepRecord(run_id=call.run_id, task_id=call.step_id)
            connection.execute(
                "INSERT OR IGNORE INTO agent_steps(run_id, step_id, status, state_json) "
                "VALUES (?, ?, ?, ?)",
                (call.run_id, call.step_id, step.status.value,
                 step.model_dump_json(exclude={"step_id"})),
            )
            row = connection.execute(
                "SELECT record_json, result_json FROM agent_tool_calls "
                "WHERE run_id = ? AND idempotency_key = ?",
                (call.run_id, call.idempotency_key),
            ).fetchone()
            if row is not None:
                result = json.loads(row["result_json"]) if row["result_json"] else None
                return AgentToolCallRecord.model_validate_json(row["record_json"]), False, result
            connection.execute(
                "INSERT INTO agent_tool_calls(tool_call_id, run_id, step_id, status, "
                "idempotency_key, record_json) VALUES (?, ?, ?, ?, ?, ?)",
                (call.tool_call_id, call.run_id, call.step_id, call.status.value,
                 call.idempotency_key, call.model_dump_json()),
            )
        return call.model_copy(deep=True), True, None

    def finish_tool_call(
        self, call: AgentToolCallRecord, *, result: dict | None = None
    ) -> None:
        with self._write_transaction() as connection:
            cursor = connection.execute(
                "UPDATE agent_tool_calls SET status = ?, record_json = ?, result_json = ? "
                "WHERE tool_call_id = ? AND status IN (?, ?)",
                (call.status.value, call.model_dump_json(),
                 json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None,
                 call.tool_call_id, AgentToolCallStatus.PENDING.value,
                 AgentToolCallStatus.RUNNING.value),
            )
            if cursor.rowcount != 1:
                raise AgentRunStoreConflictError("tool call state changed before completion")

    def get_tool_call_result(self, tool_call_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT result_json FROM agent_tool_calls WHERE tool_call_id = ?",
                (tool_call_id,),
            ).fetchone()
        return json.loads(row["result_json"]) if row and row["result_json"] else None

    def append_event(
        self,
        event: AgentEvent,
        *,
        lease_owner: str | None = None,
        now: datetime | None = None,
    ) -> AgentEvent:
        if event.sequence < -1:
            raise ValueError("event sequence cannot be less than -1")
        with self._write_transaction() as connection:
            run_row = connection.execute(
                "SELECT task_id, trace_id FROM agent_runs WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
            if run_row is None:
                raise AgentRunStoreNotFoundError(f"run not found: {event.run_id}")
            if event.task_id != str(run_row["task_id"]):
                raise AgentRunStoreConflictError("event task_id does not match run")
            if event.trace_id != str(run_row["trace_id"]):
                raise AgentRunStoreConflictError("event trace_id does not match run")
            if lease_owner is not None:
                active = connection.execute(
                    """
                    SELECT 1 FROM agent_worker_leases AS l
                    JOIN agent_runs AS r ON r.run_id = l.run_id
                    WHERE l.run_id = ? AND l.lease_owner = ?
                      AND l.lease_expires_at > ? AND r.status = ?
                    """,
                    (
                        event.run_id,
                        lease_owner,
                        _iso(_as_utc(now)),
                        AgentRunStatus.RUNNING.value,
                    ),
                ).fetchone()
                if active is None:
                    raise AgentRunStoreConflictError(
                        f"run {event.run_id} is not owned by {lease_owner}"
                    )
            sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence), -1) + 1
                    FROM agent_runtime_events WHERE run_id = ?
                    """,
                    (event.run_id,),
                ).fetchone()[0]
            )
            persisted = event.model_copy(update={"sequence": sequence}, deep=True)
            try:
                connection.execute(
                    """
                    INSERT INTO agent_runtime_events(
                        event_id, run_id, sequence, task_id, trace_id,
                        event_type, timestamp, elapsed_ms, step_id,
                        tool_call_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persisted.event_id,
                        persisted.run_id,
                        persisted.sequence,
                        persisted.task_id,
                        persisted.trace_id,
                        persisted.event_type.value,
                        persisted.timestamp,
                        persisted.elapsed_ms,
                        persisted.step_id,
                        persisted.tool_call_id,
                        json.dumps(persisted.payload, ensure_ascii=False, sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AgentRunStoreConflictError(
                    f"event already exists: {persisted.event_id}"
                ) from exc
        return persisted

    def list_events(self, run_id: str) -> tuple[AgentEvent, ...]:
        return self.list_events_after(run_id, after_sequence=-1)

    def list_events_after(
        self, run_id: str, *, after_sequence: int = -1
    ) -> tuple[AgentEvent, ...]:
        if after_sequence < -1:
            raise ValueError("after_sequence cannot be less than -1")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_runtime_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (run_id, after_sequence),
            ).fetchall()
        return tuple(
            AgentEvent(
                event_id=str(row["event_id"]),
                event_type=AgentEventType(str(row["event_type"])),
                payload=json.loads(str(row["payload_json"])),
                task_id=str(row["task_id"]),
                run_id=str(row["run_id"]),
                trace_id=str(row["trace_id"]),
                step_id=str(row["step_id"]),
                tool_call_id=str(row["tool_call_id"]),
                elapsed_ms=int(row["elapsed_ms"]),
                sequence=int(row["sequence"]),
                timestamp=str(row["timestamp"]),
            )
            for row in rows
        )

    def close(self) -> None:
        self._closed = True


__all__ = [
    "AGENT_RUNTIME_SCHEMA_VERSION",
    "DEFAULT_AGENT_RUNTIME_FILENAME",
    "AgentRunStore",
    "AgentRunStoreConflictError",
    "AgentRunStoreError",
    "AgentRunStoreNotFoundError",
]
