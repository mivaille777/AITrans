"""In-memory Sandbox run history and live events for the debug UI."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Condition, Event, Lock
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import WebSocketDisconnect

from backend.models.sandbox_debug import (
    SandboxActivityEvent,
    SandboxDebugFile,
    SandboxDebugStage,
    SandboxDebugTrace,
    SandboxEffectivePolicy,
    SandboxRunStatus,
    SandboxRunSummary,
)
from backend.sandbox.environment import (
    known_secret_environment_values,
    redact_known_secret_values,
)
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY

_STAGE_LABELS = {
    "request": "Request",
    "workspace": "Workspace",
    "staging": "Staging",
    "create": "Container",
    "start": "Start",
    "execute": "Execute",
    "collect": "Collect",
    "cleanup": "Cleanup",
}
_TERMINAL = {
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "output_limit_exceeded",
    "oom_killed",
}


class SandboxDebugError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _RunEntry:
    def __init__(self, trace: SandboxDebugTrace) -> None:
        self.trace = trace
        self.events: list[dict[str, Any]] = []
        self.stage_started: dict[str, float] = {}
        self.started_monotonic = monotonic()
        self.cancel_event = Event()
        self.future: Future[None] | None = None


class SandboxDebugService:
    """Own bounded run records while avoiding persistence of user code/output."""

    def __init__(
        self,
        *,
        max_runs: int = 100,
        max_active_runs: int = 4,
        secret_values_provider: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self.max_runs = max(1, int(max_runs))
        self.max_active_runs = max(1, int(max_active_runs))
        self._condition = Condition(Lock())
        self._runs: OrderedDict[str, _RunEntry] = OrderedDict()
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="sandbox-debug",
        )
        self._secret_values_provider = (
            secret_values_provider or known_secret_environment_values
        )
        self._closed = False

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _policy(manager: Any | None) -> SandboxEffectivePolicy:
        policy = getattr(manager, "policy", None) or DEFAULT_SANDBOX_POLICY
        return SandboxEffectivePolicy(
            network=str(getattr(policy, "network_mode", "none")),
            root_filesystem_read_only=bool(getattr(policy, "read_only_rootfs", True)),
            user=str(getattr(policy, "user", "10001:10001")),
            cap_drop=list(getattr(policy, "cap_drop", ("ALL",))),
            no_new_privileges=bool(getattr(policy, "no_new_privileges", True)),
            seccomp="default",
            cpu_limit=float(getattr(policy, "nano_cpus", 1_000_000_000)) / 1_000_000_000,
            memory_limit_bytes=int(getattr(policy, "memory_limit_bytes", 0)),
            pids_limit=int(getattr(policy, "pids_limit", 0)),
            timeout_seconds=float(getattr(policy, "timeout_seconds", 0)),
            stdout_limit_bytes=int(getattr(policy, "stdout_limit_bytes", 0)),
            stderr_limit_bytes=int(getattr(policy, "stderr_limit_bytes", 0)),
            output_limit_bytes=int(getattr(policy, "max_total_output_bytes", 0)),
            docker_socket_mounted=False,
        )

    def start_manual_run(
        self,
        *,
        code: str,
        filesystem_workspace_id: str,
        manager: Any,
        workspace_service: Any,
    ) -> SandboxRunSummary:
        workspace_name = ""
        if filesystem_workspace_id:
            try:
                workspace = workspace_service.get(filesystem_workspace_id)
            except Exception as exc:
                raise SandboxDebugError("workspace_not_found", "Filesystem workspace not found.", status_code=404) from exc
            if workspace.status != "active":
                raise SandboxDebugError("workspace_unavailable", "Filesystem workspace is unavailable.", status_code=409)
            workspace_name = workspace.display_name

        summary = SandboxRunSummary(
            sandbox_id=f"sb_{uuid4().hex}",
            run_id=f"run_{uuid4().hex}",
            source="manual",
            workspace_id=filesystem_workspace_id,
            workspace_name=workspace_name,
            runtime="docker",
            image=str(getattr(manager, "image", "") or ""),
            status="pending",
            started_at=self._now(),
        )
        trace = self._new_trace(summary, manager, initial_status="pending")
        entry = self._add_entry(trace)
        self._set_stage(summary.sandbox_id, "request", "complete", "Debug request accepted.")
        self._set_run_status(summary.sandbox_id, "preparing")
        entry.future = self._executor.submit(
            self._run_manual,
            summary.sandbox_id,
            code,
            filesystem_workspace_id,
            manager,
            workspace_service,
        )
        return self.get_run(summary.sandbox_id).run

    def begin_agent_run(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        filesystem_workspace_id: str = "",
        workspace_name: str = "",
        input_manifest: tuple[dict[str, object], ...] = (),
        manager: Any,
    ) -> tuple[str, Callable[[str, str, str], None]]:
        summary = SandboxRunSummary(
            sandbox_id=f"sb_{uuid4().hex}",
            run_id=run_id or f"run_{uuid4().hex}",
            tool_call_id=tool_call_id,
            source="agent",
            workspace_id=filesystem_workspace_id,
            workspace_name=workspace_name,
            runtime="docker",
            image=str(getattr(manager, "image", "") or ""),
            status="running",
            started_at=self._now(),
        )
        trace = self._new_trace(summary, manager, initial_status="running")
        sandbox_id = summary.sandbox_id
        self._add_entry(trace)
        self._set_stage(sandbox_id, "request", "complete", "Agent requested Python execution.")
        self._set_stage(
            sandbox_id,
            "workspace",
            "complete",
            "No host workspace selected." if not filesystem_workspace_id else "Workspace capability resolved.",
        )
        self._set_stage(sandbox_id, "staging", "running", "Preparing bounded input files.")
        with self._condition:
            entry = self._runs[sandbox_id]
            entry.trace = entry.trace.model_copy(
                update={
                    "input_files": [SandboxDebugFile.model_validate(item) for item in input_manifest]
                }
            )
        for item in input_manifest:
            self._add_activity(
                sandbox_id,
                kind="file",
                action="copy",
                target=str(item.get("relative_path", "")),
                decision="allowed",
                reason="Copied into the sandbox input mount, which is read-only.",
            )
        return sandbox_id, lambda key, status, note: self._set_stage(
            sandbox_id, key, status, note
        )

    def finish_agent_run(
        self,
        sandbox_id: str,
        result: SandboxExecutionResult,
    ) -> SandboxDebugTrace:
        return self._finish_result(sandbox_id, result)

    def fail_agent_run(self, sandbox_id: str, error: Exception) -> None:
        self._finish_error(sandbox_id, error)

    def _run_manual(
        self,
        sandbox_id: str,
        code: str,
        filesystem_workspace_id: str,
        manager: Any,
        workspace_service: Any,
    ) -> None:
        try:
            entry = self._get_entry(sandbox_id)
            if entry.cancel_event.is_set():
                self._finish_cancelled(sandbox_id)
                return
            input_files = ()
            if filesystem_workspace_id:
                self._set_stage(sandbox_id, "workspace", "running", "Resolving selected folder capability.")
                snapshot = workspace_service.snapshot(filesystem_workspace_id)
                self._set_stage(sandbox_id, "workspace", "complete", "Selected folder resolved; host path remains private.")
                with self._condition:
                    current = self._runs[sandbox_id]
                    current.trace = current.trace.model_copy(
                        update={
                            "run": current.trace.run.model_copy(
                                update={"workspace_name": snapshot.workspace.display_name}
                            ),
                            "input_files": [
                                SandboxDebugFile.model_validate(item)
                                for item in snapshot.manifest
                            ],
                        }
                    )
                for item in snapshot.manifest:
                    self._add_activity(
                        sandbox_id,
                        kind="file",
                        action="copy",
                        target=str(item.get("relative_path", "")),
                        decision="allowed",
                        reason="Copied into the sandbox input mount, which is read-only.",
                    )
                input_files = snapshot.input_files
            else:
                self._set_stage(sandbox_id, "workspace", "complete", "No host workspace selected.")

            if entry.cancel_event.is_set():
                self._finish_cancelled(sandbox_id)
                return
            self._set_run_status(sandbox_id, "running")
            result = manager.execute_python(
                code,
                input_files=input_files,
                sandbox_id=sandbox_id,
                on_stage=lambda key, status, note: self._set_stage(
                    sandbox_id, key, status, note
                ),
                cancel_event=entry.cancel_event,
            )
            self._finish_result(sandbox_id, result)
        except Exception as exc:  # noqa: BLE001 - surfaced as a bounded debug trace.
            self._finish_error(sandbox_id, exc)

    def _new_trace(
        self,
        summary: SandboxRunSummary,
        manager: Any | None,
        *,
        initial_status: SandboxRunStatus,
    ) -> SandboxDebugTrace:
        stages = [
            SandboxDebugStage(key=key, label=label)
            for key, label in _STAGE_LABELS.items()
        ]
        return SandboxDebugTrace(
            run=summary.model_copy(update={"status": initial_status}),
            stages=stages,
            policy=self._policy(manager),
        )

    def _add_entry(self, trace: SandboxDebugTrace) -> _RunEntry:
        with self._condition:
            if self._closed:
                raise SandboxDebugError("service_closed", "Sandbox debug service is shutting down.", status_code=503)
            active = sum(1 for entry in self._runs.values() if entry.trace.run.status not in _TERMINAL)
            if active >= self.max_active_runs:
                raise SandboxDebugError("sandbox_busy", "Too many Sandbox runs are active.", status_code=429)
            sandbox_id = trace.run.sandbox_id
            entry = _RunEntry(trace)
            self._runs[sandbox_id] = entry
            self._trim_history()
            self._condition.notify_all()
            return entry

    def _trim_history(self) -> None:
        while len(self._runs) > self.max_runs:
            removable = next(
                (key for key, value in self._runs.items() if value.trace.run.status in _TERMINAL),
                None,
            )
            if removable is None:
                break
            self._runs.pop(removable, None)

    def _get_entry(self, sandbox_id: str) -> _RunEntry:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            return entry

    def _set_run_status(self, sandbox_id: str, status: SandboxRunStatus) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                return
            entry.trace = entry.trace.model_copy(
                update={"run": entry.trace.run.model_copy(update={"status": status})}
            )
            self._record_event_locked(entry, {"type": "trace", "trace": entry.trace.model_dump(mode="json")})

    def _set_stage(self, sandbox_id: str, key: str, status: str, note: str) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                return
            if key not in _STAGE_LABELS or status not in {"pending", "running", "complete", "failed", "skipped"}:
                return
            now = monotonic()
            if status == "running":
                entry.stage_started[key] = now
            current_stage = next(stage for stage in entry.trace.stages if stage.key == key)
            elapsed = current_stage.elapsed_ms
            if key in entry.stage_started and status in {"complete", "failed", "skipped"}:
                elapsed = max(0, int((now - entry.stage_started.pop(key)) * 1000))
            stages = [
                stage.model_copy(update={"status": status, "elapsed_ms": elapsed, "note": note})
                if stage.key == key
                else stage
                for stage in entry.trace.stages
            ]
            entry.trace = entry.trace.model_copy(update={"stages": stages})
            self._record_event_locked(
                entry,
                {"type": "stage", "stage": next(stage.model_dump(mode="json") for stage in stages if stage.key == key)},
            )

    def _add_activity(
        self,
        sandbox_id: str,
        *,
        kind: str,
        action: str,
        target: str,
        decision: str,
        reason: str,
    ) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                return
            sequence = len(entry.trace.activities)
            activity = SandboxActivityEvent(
                sequence=sequence,
                timestamp=self._now(),
                kind=kind,
                action=action,
                target=target,
                decision=decision,
                reason=reason,
            )
            entry.trace = entry.trace.model_copy(
                update={"activities": [*entry.trace.activities, activity]}
            )
            self._record_event_locked(
                entry,
                {"type": "activity", "activity": activity.model_dump(mode="json")},
            )

    def _finish_result(self, sandbox_id: str, result: SandboxExecutionResult) -> SandboxDebugTrace:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            now = self._now()
            status = result.status
            known_secrets = self._secret_values_provider()
            entry.trace = entry.trace.model_copy(
                update={
                    "run": entry.trace.run.model_copy(
                        update={
                            "status": status,
                            "finished_at": now,
                            "duration_ms": result.duration_ms,
                            "exit_code": result.exit_code,
                            "runtime": result.runtime,
                            "image": result.image or entry.trace.run.image,
                        }
                    ),
                    "stdout": redact_known_secret_values(
                        result.stdout,
                        secret_values=known_secrets,
                    ),
                    "stderr": redact_known_secret_values(
                        result.stderr,
                        secret_values=known_secrets,
                    ),
                    "output_files": [
                        SandboxDebugFile(
                            file_id=item.file_id,
                            relative_path=item.relative_path,
                            size_bytes=item.size_bytes,
                            sha256=item.sha256,
                            source="generated",
                        )
                        for item in result.output_files
                    ],
                    "error": self._result_message(result),
                }
            )
            self._complete_remaining_stages(entry, status)
            self._record_event_locked(
                entry,
                {"type": "terminal", "trace": entry.trace.model_dump(mode="json")},
            )
            return entry.trace

    def _finish_error(self, sandbox_id: str, error: Exception) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None or entry.trace.run.status in _TERMINAL:
                return
            now = self._now()
            message = str(error).strip() or type(error).__name__
            # Host paths must never be included in this user-facing trace.
            if ":\\" in message or message.startswith("/"):
                message = "Sandbox execution failed."
            message = redact_known_secret_values(
                message,
                secret_values=self._secret_values_provider(),
            )
            entry.trace = entry.trace.model_copy(
                update={
                    "run": entry.trace.run.model_copy(
                        update={
                            "status": "failed",
                            "finished_at": now,
                            "duration_ms": max(0, int((monotonic() - entry.started_monotonic) * 1000)),
                        }
                    ),
                    "error": message[:1000],
                }
            )
            self._complete_remaining_stages(entry, "failed")
            self._record_event_locked(
                entry,
                {"type": "terminal", "trace": entry.trace.model_dump(mode="json")},
            )

    def _finish_cancelled(self, sandbox_id: str) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None or entry.trace.run.status in _TERMINAL:
                return
            entry.trace = entry.trace.model_copy(
                update={
                    "run": entry.trace.run.model_copy(
                        update={
                            "status": "cancelled",
                            "finished_at": self._now(),
                            "duration_ms": max(0, int((monotonic() - entry.started_monotonic) * 1000)),
                        }
                    )
                }
            )
            self._complete_remaining_stages(entry, "cancelled")
            self._record_event_locked(
                entry,
                {"type": "terminal", "trace": entry.trace.model_dump(mode="json")},
            )

    def _complete_remaining_stages(self, entry: _RunEntry, terminal_status: str) -> None:
        stages: list[SandboxDebugStage] = []
        for stage in entry.trace.stages:
            if stage.status in {"complete", "failed", "skipped"}:
                stages.append(stage)
                continue
            if stage.status == "running" and terminal_status == "failed":
                stages.append(
                    stage.model_copy(update={"status": "failed", "note": "Sandbox run failed."})
                )
            else:
                stages.append(
                    stage.model_copy(
                        update={
                            "status": "skipped",
                            "note": "Not reached before the run ended.",
                        }
                    )
                )
        entry.trace = entry.trace.model_copy(update={"stages": stages})

    @staticmethod
    def _result_message(result: SandboxExecutionResult) -> str:
        if result.status == "timed_out":
            return "Python execution timed out."
        if result.status == "output_limit_exceeded":
            return "Python execution exceeded the output limit."
        if result.status == "oom_killed":
            return "Python execution exceeded the memory limit."
        if result.status == "cancelled":
            return "Python execution was cancelled."
        if result.status == "failed":
            return f"Python execution exited with code {result.exit_code}." if result.exit_code is not None else "Python execution failed."
        return ""

    def _record_event_locked(self, entry: _RunEntry, event: dict[str, Any]) -> None:
        entry.events.append(event)
        self._condition.notify_all()

    def list_runs(self) -> list[SandboxRunSummary]:
        with self._condition:
            return [entry.trace.run for entry in reversed(self._runs.values())]

    def get_run(self, sandbox_id: str) -> SandboxDebugTrace:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            return entry.trace

    def cancel(self, sandbox_id: str, manager: Any) -> SandboxRunSummary:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            if entry.trace.run.status in _TERMINAL:
                return entry.trace.run
            if entry.trace.run.source != "manual":
                raise SandboxDebugError("agent_run_cancel_unsupported", "Agent-managed sandbox runs cannot be cancelled here.", status_code=409)
            entry.cancel_event.set()
            future = entry.future
        if future is not None and future.cancel():
            self._finish_cancelled(sandbox_id)
        else:
            manager.cancel(sandbox_id)
        return self.get_run(sandbox_id).run

    def wait_events(
        self,
        sandbox_id: str,
        after_index: int,
        *,
        timeout: float = 0.5,
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            if after_index >= len(entry.events) and entry.trace.run.status not in _TERMINAL:
                self._condition.wait(timeout=max(0.0, timeout))
                entry = self._runs.get(sandbox_id)
                if entry is None:
                    raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            events = entry.events[after_index:]
            complete = entry.trace.run.status in _TERMINAL and after_index + len(events) >= len(entry.events)
            return [dict(event) for event in events], complete

    async def stream(self, websocket: Any, sandbox_id: str) -> None:
        await websocket.accept()
        cursor = 0
        try:
            while True:
                events, complete = await asyncio.to_thread(
                    self.wait_events,
                    sandbox_id,
                    cursor,
                    timeout=0.5,
                )
                if not events and cursor == 0:
                    trace = self.get_run(sandbox_id)
                    await websocket.send_json({"type": "trace", "trace": trace.model_dump(mode="json")})
                for event in events:
                    await websocket.send_json(event)
                    cursor += 1
                if complete:
                    return
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            # Disconnect and cancelled ASGI sends are normal stream termination.
            return

    def close(self) -> None:
        with self._condition:
            self._closed = True
            entries = list(self._runs.values())
            for entry in entries:
                if entry.trace.run.status not in _TERMINAL:
                    entry.cancel_event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)


__all__ = ["SandboxDebugError", "SandboxDebugService"]
