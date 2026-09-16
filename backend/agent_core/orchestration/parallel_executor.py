from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack, closing
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, RLock
from time import time
from typing import Any
from uuid import uuid4

from backend.agent_core.exceptions import AgentBudgetExceededError, AgentCancelledError
from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector
from backend.agent_core.orchestration.reducer import reduce_task_results
from backend.agent_core.orchestration.runtime_budget import bind_runtime_budget
from backend.agent_core.orchestration.serial_executor import (
    SerialExecution,
    SpecialistExecution,
    SpecialistExecutor,
)
from backend.agent_core.reliability import AgentRunControl
from backend.models.agent_tasks import (
    ResourceUsage,
    ScopeContext,
    TaskResult,
    TaskRole,
    TaskSpec,
    TaskStatus,
    ValidatedTaskPlan,
    utc_now,
)

_GLOBAL_EXPERT_SLOTS = BoundedSemaphore(2)
_GLOBAL_GPU_SLOTS = BoundedSemaphore(1)
_GPU_TOOL_MARKERS = ("gpu", "image", "vision", "embedding", "rerank", "ocr")


@dataclass(frozen=True, slots=True)
class ParallelExecutionPolicy:
    max_parallel_experts: int = 2
    max_model_calls: int = 8
    max_tool_calls: int = 16
    max_retrievals: int = 8
    max_retries: int = 1
    lease_seconds: float = 90.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_parallel_experts <= 2:
            raise ValueError("max_parallel_experts must be between 1 and 2")
        for value in (
            self.max_model_calls,
            self.max_tool_calls,
            self.max_retrievals,
        ):
            if value < 0:
                raise ValueError("resource budgets must be non-negative")
        if self.max_retries not in {0, 1}:
            raise ValueError("max_retries must be 0 or 1")
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")


class SharedRunBudget:
    """Thread-safe reservation ledger shared by every task in one run."""

    def __init__(self, policy: ParallelExecutionPolicy) -> None:
        self._limits = {
            "model_calls": policy.max_model_calls,
            "tool_calls": policy.max_tool_calls,
            "retrievals": policy.max_retrievals,
        }
        self._reserved = {key: 0 for key in self._limits}
        self._usage = ResourceUsage()
        self._lock = RLock()

    def reserve(self, resource: str, amount: int = 1) -> bool:
        requested = max(0, int(amount))
        with self._lock:
            if resource not in self._limits:
                raise ValueError(f"unknown budget resource: {resource}")
            if self._reserved[resource] + requested > self._limits[resource]:
                return False
            self._reserved[resource] += requested
            return True

    def record(self, usage: ResourceUsage) -> None:
        with self._lock:
            self._usage = ResourceUsage(
                input_tokens=_optional_sum(self._usage.input_tokens, usage.input_tokens),
                output_tokens=_optional_sum(self._usage.output_tokens, usage.output_tokens),
                tool_calls=self._usage.tool_calls + usage.tool_calls,
                model_calls=self._usage.model_calls + usage.model_calls,
                elapsed_ms=_optional_sum(self._usage.elapsed_ms, usage.elapsed_ms),
            )

    @property
    def usage(self) -> ResourceUsage:
        with self._lock:
            return self._usage.model_copy(deep=True)


def _optional_sum(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return int(left or 0) + int(right or 0)


class TaskCheckpointConflictError(RuntimeError):
    pass


class TaskRunLeaseError(RuntimeError):
    pass


class SQLiteTaskCheckpointStore:
    """Durable task frontier/results and a single-owner run lease.

    It intentionally shares the root LangGraph checkpoint database path while
    using separate tables and separate short-lived WAL connections.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], float] = time,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS multi_agent_task_runs (
                    run_id TEXT PRIMARY KEY,
                    plan_hash TEXT NOT NULL,
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_expires_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS multi_agent_task_checkpoints (
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    attempt_ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '',
                    output_json TEXT NOT NULL DEFAULT 'null',
                    direct_delivery INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (run_id, task_id),
                    FOREIGN KEY (run_id) REFERENCES multi_agent_task_runs(run_id)
                        ON DELETE CASCADE
                );
                """
            )

    def acquire_lease(
        self,
        *,
        run_id: str,
        plan_hash: str,
        owner_id: str,
        lease_seconds: float,
    ) -> bool:
        now = self._clock()
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM multi_agent_task_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is not None and str(row["plan_hash"]) != plan_hash:
                connection.rollback()
                raise TaskCheckpointConflictError(
                    "run_id is already bound to a different validated task plan"
                )
            if row is not None:
                holder = str(row["lease_owner"])
                expires = float(row["lease_expires_at"])
                if holder and holder != owner_id and expires > now:
                    connection.rollback()
                    return False
            connection.execute(
                """
                INSERT INTO multi_agent_task_runs(
                    run_id, plan_hash, lease_owner, lease_expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    lease_owner = excluded.lease_owner,
                    lease_expires_at = excluded.lease_expires_at,
                    updated_at = excluded.updated_at
                """,
                (run_id, plan_hash, owner_id, now + lease_seconds, now),
            )
            connection.commit()
            return True

    def heartbeat(self, run_id: str, owner_id: str, lease_seconds: float) -> None:
        now = self._clock()
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE multi_agent_task_runs SET lease_expires_at = ?, updated_at = ?
                WHERE run_id = ? AND lease_owner = ?
                """,
                (now + lease_seconds, now, run_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise TaskRunLeaseError("multi-agent run lease was lost")

    def release_lease(self, run_id: str, owner_id: str) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE multi_agent_task_runs SET lease_owner = '', lease_expires_at = 0,
                    updated_at = ? WHERE run_id = ? AND lease_owner = ?
                """,
                (self._clock(), run_id, owner_id),
            )

    def begin_task(
        self,
        *,
        run_id: str,
        task_id: str,
        plan_hash: str,
        attempt_ordinal: int,
    ) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO multi_agent_task_checkpoints(
                    run_id, task_id, plan_hash, attempt_ordinal, status, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                ON CONFLICT(run_id, task_id) DO UPDATE SET
                    attempt_ordinal = excluded.attempt_ordinal,
                    status = 'running', result_json = '', output_json = 'null',
                    direct_delivery = 0, updated_at = excluded.updated_at
                """,
                (run_id, task_id, plan_hash, attempt_ordinal, self._clock()),
            )

    def complete_task(
        self,
        *,
        run_id: str,
        plan_hash: str,
        execution: SpecialistExecution,
    ) -> None:
        result = execution.result
        try:
            output_json = json.dumps(
                execution.output, ensure_ascii=False, sort_keys=True, default=str
            )
        except (TypeError, ValueError):
            output_json = "null"
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE multi_agent_task_checkpoints SET status = ?, result_json = ?,
                    output_json = ?, direct_delivery = ?, updated_at = ?
                WHERE run_id = ? AND task_id = ? AND plan_hash = ?
                """,
                (
                    result.status.value,
                    result.model_dump_json(),
                    output_json,
                    int(execution.direct_delivery),
                    self._clock(),
                    run_id,
                    result.task_id,
                    plan_hash,
                ),
            )

    def load(self, run_id: str, plan_hash: str) -> tuple[dict[str, SpecialistExecution], set[str]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM multi_agent_task_checkpoints
                WHERE run_id = ? AND plan_hash = ? ORDER BY task_id
                """,
                (run_id, plan_hash),
            ).fetchall()
        completed: dict[str, SpecialistExecution] = {}
        interrupted: set[str] = set()
        for row in rows:
            if str(row["status"]) == "running":
                interrupted.add(str(row["task_id"]))
                continue
            if not str(row["result_json"]):
                continue
            completed[str(row["task_id"])] = SpecialistExecution(
                result=TaskResult.model_validate_json(str(row["result_json"])),
                output=json.loads(str(row["output_json"])),
                direct_delivery=bool(row["direct_delivery"]),
            )
        return completed, interrupted


class ParallelTaskGraphExecutor:
    """Bounded fan-out/fan-in scheduler around typed LangGraph specialists."""

    def __init__(
        self,
        executors: Mapping[TaskRole, SpecialistExecutor],
        *,
        policy: ParallelExecutionPolicy | None = None,
        checkpoint_store: SQLiteTaskCheckpointStore | None = None,
        artifact_store: Any | None = None,
    ) -> None:
        self._executors = dict(executors)
        self.policy = policy or ParallelExecutionPolicy()
        self.checkpoints = checkpoint_store
        self._artifacts = artifact_store

    @staticmethod
    def _plan_hash(plan: ValidatedTaskPlan) -> str:
        payload = plan.model_dump_json(exclude_none=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _emit(
        collector: MultiAgentTraceCollector | None,
        event_type: str,
        *,
        task: TaskSpec | None = None,
        status: str,
        attempt: int = 0,
        reason_code: str = "",
        usage: ResourceUsage | None = None,
    ) -> None:
        if collector is None:
            return
        collector.emit(
            event_type,
            actor=task.role.value if task is not None else "supervisor",
            status=status,
            payload={
                "task_id": task.task_id if task is not None else "",
                "parent_task_id": "",
                "attempt": attempt,
                "plan_revision": task.plan_revision if task is not None else 0,
                "reason_code": reason_code,
                "usage": (usage or ResourceUsage()).model_dump(mode="json"),
            },
        )

    def _execute_one(
        self,
        task: TaskSpec,
        *,
        scope: ScopeContext,
        dependency_results: Mapping[str, TaskResult],
        memory_snapshot: Mapping[str, Any],
        control: AgentRunControl,
        collector: MultiAgentTraceCollector | None,
        attempt: int,
        budget: SharedRunBudget,
    ) -> SpecialistExecution:
        started_at = utc_now()
        with ExitStack() as resources:
            resources.enter_context(_GLOBAL_EXPERT_SLOTS)
            if any(
                marker in tool.casefold()
                for tool in task.allowed_tools
                for marker in _GPU_TOOL_MARKERS
            ):
                resources.enter_context(_GLOBAL_GPU_SLOTS)
            control.checkpoint(f"multi_agent_task:{task.task_id}")
            self._emit(
                collector,
                "task_progress",
                task=task,
                status="running",
                attempt=attempt,
                reason_code="specialist_invoked",
            )
            executor = self._executors.get(task.role)
            if executor is None:
                return SpecialistExecution(
                    result=TaskResult(
                        task_id=task.task_id,
                        attempt_id=f"{task.task_id}:{attempt}",
                        attempt_ordinal=attempt,
                        status=TaskStatus.BLOCKED,
                        error_code="specialist_not_registered",
                    )
                )
            try:
                with bind_runtime_budget(budget):
                    execution = executor.execute(
                        task=task,
                        scope=scope,
                        dependency_results=dependency_results,
                        memory_snapshot=dict(memory_snapshot),
                    )
            except AgentBudgetExceededError:
                return SpecialistExecution(
                    result=TaskResult(
                        task_id=task.task_id,
                        attempt_id=f"{task.task_id}:{attempt}",
                        attempt_ordinal=attempt,
                        status=TaskStatus.BLOCKED,
                        error_code="budget_exhausted",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - task failure is isolated
                return SpecialistExecution(
                    result=TaskResult(
                        task_id=task.task_id,
                        attempt_id=f"{task.task_id}:{attempt}",
                        attempt_ordinal=attempt,
                        status=TaskStatus.FAILED,
                        error_code=type(exc).__name__,
                    )
                )
            if execution.result.task_id != task.task_id:
                raise ValueError("specialist returned a result for a different task")
            payload = execution.result.model_dump(
                mode="json",
                exclude={"content_hash"},
            )
            payload.update(
                {
                    "attempt_id": f"{task.task_id}:{attempt}",
                    "attempt_ordinal": attempt,
                    "started_at": started_at,
                    "finished_at": utc_now(),
                }
            )
            return SpecialistExecution(
                result=TaskResult.model_validate(payload),
                output=execution.output,
                direct_delivery=execution.direct_delivery,
            )

    def _revoke_late(self, execution: SpecialistExecution) -> None:
        if self._artifacts is None:
            return
        for ref in execution.result.artifact_refs:
            try:
                self._artifacts.revoke(
                    ref.artifact_id,
                    ref.version,
                    reason="cancelled_attempt_fence",
                )
            except Exception:  # noqa: BLE001,S110 - cancellation cleanup is best effort
                pass

    def execute(
        self,
        *,
        plan: ValidatedTaskPlan,
        scope: ScopeContext,
        memory_snapshot: Mapping[str, Any] | None = None,
        run_id: str = "",
        collector: MultiAgentTraceCollector | None = None,
        control: AgentRunControl | None = None,
    ) -> SerialExecution:
        active_control = control or AgentRunControl()
        active_run_id = str(run_id or getattr(collector, "run_id", "") or uuid4().hex)
        plan_hash = self._plan_hash(plan)
        owner_id = f"scheduler-{uuid4().hex}"
        resumed: dict[str, SpecialistExecution] = {}
        interrupted: set[str] = set()
        lease_acquired = False
        if self.checkpoints is not None:
            lease_acquired = self.checkpoints.acquire_lease(
                run_id=active_run_id,
                plan_hash=plan_hash,
                owner_id=owner_id,
                lease_seconds=self.policy.lease_seconds,
            )
            if not lease_acquired:
                raise TaskRunLeaseError("multi-agent run already has an active owner")
            resumed, interrupted = self.checkpoints.load(active_run_id, plan_hash)
            if resumed or interrupted:
                self._emit(
                    collector,
                    "workflow_resumed",
                    status="running",
                    reason_code="task_checkpoint_restored",
                )

        pending = plan.task_map()
        by_id: dict[str, TaskResult] = {}
        outputs: dict[str, Any] = {}
        results: list[TaskResult] = []
        direct_output: Any = None
        direct_delivery = False
        non_leaf = {dependency for task in plan.tasks for dependency in task.depends_on}
        budget = SharedRunBudget(self.policy)
        futures: dict[Future[SpecialistExecution], tuple[TaskSpec, int]] = {}
        pool = ThreadPoolExecutor(
            max_workers=self.policy.max_parallel_experts,
            thread_name_prefix=f"ma-{active_run_id[:16]}",
        )
        deferred_lease_release = False

        def merge(task: TaskSpec, execution: SpecialistExecution, *, restored: bool = False) -> None:
            nonlocal results, direct_output, direct_delivery
            result = execution.result
            by_id[task.task_id] = result
            results = reduce_task_results(results, [result])
            budget.record(result.usage)
            if execution.output is not None:
                outputs[task.task_id] = execution.output
            if execution.direct_delivery and task.task_id not in non_leaf:
                direct_output = execution.output
                direct_delivery = True
            event_type = {
                TaskStatus.SUCCEEDED: "task_completed",
                TaskStatus.PARTIAL: "task_partial",
                TaskStatus.FAILED: "task_failed",
                TaskStatus.BLOCKED: "task_blocked",
                TaskStatus.CANCELLED: "task_cancelled",
                TaskStatus.SKIPPED: "task_skipped",
            }[result.status]
            if result.error_code == "budget_exhausted":
                self._emit(
                    collector,
                    "budget_exhausted",
                    task=task,
                    status="blocked",
                    attempt=result.attempt_ordinal,
                    reason_code="task_resource_budget_exhausted",
                    usage=result.usage,
                )
            self._emit(
                collector,
                event_type,
                task=task,
                status=result.status.value,
                attempt=result.attempt_ordinal,
                reason_code=("checkpoint_reused" if restored else result.error_code),
                usage=result.usage,
            )
            if result.artifact_refs:
                self._emit(
                    collector,
                    "artifact_verified" if result.status is TaskStatus.SUCCEEDED else "artifact_rejected",
                    task=task,
                    status=result.status.value,
                    attempt=result.attempt_ordinal,
                    reason_code=result.error_code,
                )

        try:
            for task_id, execution in resumed.items():
                task = pending.get(task_id)
                if task is not None:
                    merge(task, execution, restored=True)
                    pending.pop(task_id)

            while pending or futures:
                active_control.checkpoint("multi_agent_scheduler")
                if self.checkpoints is not None:
                    self.checkpoints.heartbeat(
                        active_run_id, owner_id, self.policy.lease_seconds
                    )
                ready = [
                    task
                    for task in pending.values()
                    if all(dependency in by_id for dependency in task.depends_on)
                ]
                for task in sorted(ready, key=lambda item: item.task_id):
                    if len(futures) >= self.policy.max_parallel_experts:
                        break
                    dependency_results = {
                        dependency: by_id[dependency] for dependency in task.depends_on
                    }
                    failed = [
                        item
                        for item in dependency_results.values()
                        if item.status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL}
                    ]
                    if failed:
                        dependency_status = (
                            TaskStatus.BLOCKED if task.required else TaskStatus.SKIPPED
                        )
                        execution = SpecialistExecution(
                            result=TaskResult(
                                task_id=task.task_id,
                                attempt_id=f"{task.task_id}:1",
                                status=dependency_status,
                                error_code="dependency_unavailable",
                                unmet_requirements=sorted(item.task_id for item in failed),
                            )
                        )
                        merge(task, execution)
                        pending.pop(task.task_id)
                        continue
                    self._emit(collector, "task_ready", task=task, status="ready")
                    if not budget.reserve("model_calls", 1):
                        self._emit(
                            collector,
                            "budget_exhausted",
                            task=task,
                            status="blocked",
                            reason_code="model_call_budget_exhausted",
                        )
                        exhausted_status = (
                            TaskStatus.BLOCKED if task.required else TaskStatus.SKIPPED
                        )
                        execution = SpecialistExecution(
                            result=TaskResult(
                                task_id=task.task_id,
                                attempt_id=f"{task.task_id}:1",
                                status=exhausted_status,
                                error_code="budget_exhausted",
                            )
                        )
                        merge(task, execution)
                        pending.pop(task.task_id)
                        continue
                    attempt = 2 if task.task_id in interrupted else 1
                    if attempt > 1:
                        self._emit(
                            collector,
                            "task_retrying",
                            task=task,
                            status="running",
                            attempt=attempt,
                            reason_code="interrupted_attempt",
                        )
                    if attempt - 1 > self.policy.max_retries:
                        execution = SpecialistExecution(
                            result=TaskResult(
                                task_id=task.task_id,
                                attempt_id=f"{task.task_id}:{attempt}",
                                attempt_ordinal=attempt,
                                status=TaskStatus.BLOCKED,
                                error_code="retry_budget_exhausted",
                            )
                        )
                        merge(task, execution)
                        pending.pop(task.task_id)
                        continue
                    if self.checkpoints is not None:
                        self.checkpoints.begin_task(
                            run_id=active_run_id,
                            task_id=task.task_id,
                            plan_hash=plan_hash,
                            attempt_ordinal=attempt,
                        )
                    self._emit(
                        collector,
                        "task_started",
                        task=task,
                        status="running",
                        attempt=attempt,
                    )
                    future = pool.submit(
                        self._execute_one,
                        task,
                        scope=scope,
                        dependency_results=dependency_results,
                        memory_snapshot=dict(memory_snapshot or {}),
                        control=active_control,
                        collector=collector,
                        attempt=attempt,
                        budget=budget,
                    )
                    futures[future] = (task, attempt)
                    pending.pop(task.task_id)

                if futures:
                    done, _ = wait(tuple(futures), timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in done:
                        task, _attempt = futures[future]
                        active_control.checkpoint(f"multi_agent_result:{task.task_id}")
                        execution = future.result()
                        active_control.checkpoint(f"multi_agent_merge:{task.task_id}")
                        futures.pop(future)
                        if self.checkpoints is not None:
                            self.checkpoints.complete_task(
                                run_id=active_run_id,
                                plan_hash=plan_hash,
                                execution=execution,
                            )
                        merge(task, execution)
                elif pending and not ready:
                    raise RuntimeError("validated task plan has no executable frontier")
        except (AgentCancelledError, AgentBudgetExceededError):
            late_futures: list[Future[SpecialistExecution]] = []
            for future, (task, attempt) in list(futures.items()):
                if future.cancel():
                    self._emit(
                        collector,
                        "task_cancelled",
                        task=task,
                        status="cancelled",
                        attempt=attempt,
                        reason_code="run_cancelled",
                    )
                else:
                    late_futures.append(future)
            if late_futures:
                deferred_lease_release = self.checkpoints is not None and lease_acquired
                remaining = {"count": len(late_futures)}
                callback_lock = RLock()

                def discard_late(item: Future[SpecialistExecution]) -> None:
                    try:
                        self._revoke_late(item.result())
                    except Exception:  # noqa: BLE001,S110 - cleanup cannot alter cancellation
                        pass
                    finally:
                        with callback_lock:
                            remaining["count"] -= 1
                            if (
                                remaining["count"] == 0
                                and self.checkpoints is not None
                                and lease_acquired
                            ):
                                self.checkpoints.release_lease(active_run_id, owner_id)

                for future in late_futures:
                    future.add_done_callback(discard_late)
            for task in pending.values():
                self._emit(
                    collector,
                    "task_cancelled",
                    task=task,
                    status="cancelled",
                    reason_code="run_cancelled_before_dispatch",
                )
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            if (
                self.checkpoints is not None
                and lease_acquired
                and not deferred_lease_release
            ):
                self.checkpoints.release_lease(active_run_id, owner_id)

        return SerialExecution(
            results=tuple(results),
            outputs=outputs,
            direct_output=direct_output,
            direct_delivery=direct_delivery,
        )


__all__ = [
    "ParallelExecutionPolicy",
    "ParallelTaskGraphExecutor",
    "SQLiteTaskCheckpointStore",
    "SharedRunBudget",
    "TaskCheckpointConflictError",
    "TaskRunLeaseError",
]
