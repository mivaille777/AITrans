"""Bounded live telemetry and opt-in persistent Sandbox debug history."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
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
    SandboxDebugWorkspaceChange,
    SandboxEffectivePolicy,
    SandboxRunStatus,
    SandboxRunSummary,
    SandboxResourceSample,
)
from backend.sandbox.command_models import SandboxCommandResult
from backend.sandbox.environment import (
    known_secret_environment_values,
    redact_known_secret_values,
)
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.ownership import current_owner, owner_alive
from backend.services.sandbox_history_store import SandboxHistoryStore

_STAGE_LABELS = {
    "request": "Request",
    "permission": "Permission",
    "approval": "Approval",
    "workspace": "Workspace",
    "staging": "Staging",
    "create": "Container",
    "start": "Start",
    "execute": "Execute",
    "network": "Network",
    "changes": "Changes",
    "apply": "Apply",
    "collect": "Collect",
    "cleanup": "Cleanup",
}
_TERMINAL = {
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "output_limit_exceeded",
    "storage_limit_exceeded",
    "interrupted",
    "oom_killed",
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![\w])(?:[a-z]:[\\/]|\\\\)[^\s\"'<>|,;]+")
_SAFE_CONTAINER_PATHS = {"/input", "/workspace"}


class SandboxDebugError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _RunEntry:
    def __init__(self, trace: SandboxDebugTrace) -> None:
        self.trace = trace
        self.events: list[dict[str, Any]] = []
        self.event_sizes: list[int] = []
        self.stage_started: dict[str, float] = {}
        self.started_monotonic = monotonic()
        self.cancel_event = Event()
        self.future: Future[None] | None = None
        self.owner = current_owner()
        self.event_base = 0
        self.last_persist = monotonic()
        self.disk_usage = {"workspace_bytes": 0, "output_bytes": 0}
        self.owned = True
        self.command = None


class SandboxDebugService:
    """Own bounded run records, retaining scrubbed code/logs only when requested."""

    def __init__(
        self,
        *,
        max_runs: int = 100,
        max_active_runs: int = 4,
        secret_values_provider: Callable[[], tuple[str, ...]] | None = None,
        history_path: Path | None = None,
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
        self._store = SandboxHistoryStore(history_path, self.max_runs) if history_path else None
        self.recovery_result: dict = {"removed": [], "failed": [], "skipped": []}
        if self._store:
            for trace, owner in self._store.load():
                entry = _RunEntry(trace)
                entry.owner, entry.owned = owner, False
                entry.event_base = trace.sequence
                if trace.run.status not in _TERMINAL and not owner_alive(owner):
                    entry.trace = trace.model_copy(update={"run": trace.run.model_copy(update={"status": "interrupted", "finished_at": self._now()}),
                                                          "error": "Backend stopped before this run completed; recovery is required."})
                    self._complete_remaining_stages(entry, "failed")
                    entry.trace = entry.trace.model_copy(update={"stages": [s.model_copy(update={"status": "pending", "note": "Awaiting abandoned-resource recovery."}) if s.key == "cleanup" else s for s in entry.trace.stages]})
                    self._store.save(entry.trace, owner, terminal=True)
                self._runs[trace.run.sandbox_id] = entry

    def recover(self, manager: Any) -> dict:
        with self._condition:
            retry_ids = {sid for sid, entry in self._runs.items() if entry.owned and entry.trace.run.status in _TERMINAL
                         and any(s.key == "cleanup" and s.status in {"failed", "pending", "skipped"} for s in entry.trace.stages)}
        result = manager.recover(completed_ids=retry_ids) if retry_ids else manager.recover()
        self.recovery_result = result
        with self._condition:
            for entry in self._runs.values():
                if entry.trace.run.status == "interrupted" or entry.trace.run.sandbox_id in retry_ids:
                    failed = entry.trace.run.sandbox_id in result["failed"]
                    skipped = entry.trace.run.sandbox_id in result["skipped"]
                    state = "failed" if failed else "skipped" if skipped else "complete"
                    note = "Recovery failed; retry runtime recovery." if failed else "Unverifiable resources preserved." if skipped else "Abandoned resources checked and recovered."
                    entry.trace = entry.trace.model_copy(update={"stages": [s.model_copy(update={"status": state, "note": note}) if s.key == "cleanup" else s for s in entry.trace.stages]})
                    self._record_event_locked(entry, {"type": "terminal"})
        return result

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
            workspace_disk_limit_bytes=int(getattr(policy, "workspace_disk_limit_bytes", 0)),
            workspace_entry_limit=int(getattr(policy, "workspace_entry_limit", 0)),
        )

    def start_manual_run(
        self,
        *,
        code: str,
        filesystem_workspace_id: str,
        manager: Any,
        workspace_service: Any,
        retain_content: bool = False,
        execution_kind: str = "python",
        argv: list[str] | None = None,
        cwd: str = ".",
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
            workspace_name=_safe_trace_text(workspace_name, limit=256),
            runtime="docker",
            image=str(getattr(manager, "image", "") or ""),
            status="pending",
            started_at=self._now(),
        )
        trace = self._new_trace(summary, manager, initial_status="pending")
        command = None
        if execution_kind == "command":
            from backend.sandbox.command_models import SandboxCommandRequest
            command = SandboxCommandRequest(argv=argv or [], cwd=cwd)
            code = json.dumps(command.argv, ensure_ascii=False)
        trace = trace.model_copy(update={"logs_retained": retain_content, "code": _safe_trace_text(code, limit=50_000, secret_values=self._secret_values_provider()) if retain_content else None,
                                        "execution_kind": execution_kind,
                                        "run": summary.model_copy(update={"code_sha256": hashlib.sha256(code.encode()).hexdigest()})})
        entry = self._add_entry(trace)
        entry.command = command
        self._set_stage(summary.sandbox_id, "request", "complete", "Debug request accepted.")
        self._set_stage(summary.sandbox_id, "permission", "running" if command else "complete", "Evaluating allowlisted command access." if command else "Manual Sandbox execution is allowed by the Debug Studio policy.")
        if command is None:
            self._add_activity(
                summary.sandbox_id,
                kind="policy",
                action="permission.request",
                target="python_execute",
                decision="observed",
                reason="Manual Sandbox execution requested from Debug Studio.",
                permission_action="python_execute",
                policy_rule="sandbox.python_execute.safe_default",
            )
            self._add_activity(
                summary.sandbox_id,
                kind="policy",
                action="permission.allow",
                target="python_execute",
                decision="allowed",
                reason="Debug Studio permits isolated Python execution.",
                permission_action="python_execute",
                policy_rule="sandbox.python_execute.safe_default",
            )
        self._set_stage(summary.sandbox_id, "approval", "skipped", "Manual execution uses the read-only profile; no host changes or network grant requested.")
        self._set_stage(summary.sandbox_id, "network", "skipped", "Network disabled by the manual read-only profile.")
        self._set_stage(summary.sandbox_id, "changes", "skipped", "No editable host changeset requested.")
        self._set_stage(summary.sandbox_id, "apply", "skipped", "No host writeback requested.")
        self._set_run_status(summary.sandbox_id, "queued")
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
        record_default_permission_events: bool = True,
        permission_action: str = "python_execute",
        permission_target: str = "python_execute",
        permission_rule: str = "sandbox.python_execute.safe_default",
        code: str = "",
        execution_kind: str = "python",
    ) -> tuple[str, Callable[[str, str, str], None]]:
        summary = SandboxRunSummary(
            sandbox_id=f"sb_{uuid4().hex}",
            run_id=run_id or f"run_{uuid4().hex}",
            tool_call_id=tool_call_id,
            source="agent",
            workspace_id=filesystem_workspace_id,
            workspace_name=_safe_trace_text(workspace_name, limit=256),
            runtime="docker",
            image=str(getattr(manager, "image", "") or ""),
            status="running",
            started_at=self._now(),
        )
        trace = self._new_trace(summary, manager, initial_status="running")
        trace = trace.model_copy(update={"execution_kind": execution_kind,
            "run": summary.model_copy(update={"code_sha256": hashlib.sha256(code.encode()).hexdigest() if code else ""})})
        sandbox_id = summary.sandbox_id
        self._add_entry(trace)
        self._set_stage(sandbox_id, "request", "complete", "Agent requested Python execution.")
        if record_default_permission_events:
            self._set_stage(sandbox_id, "permission", "complete", "Sandbox Python execution is allowed by policy.")
        else:
            self._set_stage(sandbox_id, "permission", "running", "Evaluating the requested Sandbox command.")
        if record_default_permission_events:
            self._add_activity(
                sandbox_id,
                kind="policy",
                action="permission.request",
                target=permission_target,
                decision="observed",
                reason=f"Agent requested {permission_action}.",
                permission_action=permission_action,
                policy_rule=permission_rule,
            )
            self._add_activity(
                sandbox_id,
                kind="policy",
                action="permission.allow",
                target=permission_target,
                decision="allowed",
                reason="Isolated Python execution is allowed by the Sandbox policy.",
                permission_action=permission_action,
                policy_rule=permission_rule,
            )
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
                    "input_files": [
                        _safe_debug_file(item) for item in input_manifest
                    ]
                }
            )
        for item in input_manifest:
            self._add_activity(
                sandbox_id,
                kind="file",
                action="filesystem.read",
                target=_safe_trace_relative_path(item.get("relative_path", "")),
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

    def finish_command_run(
        self,
        sandbox_id: str,
        result: SandboxCommandResult,
    ) -> SandboxDebugTrace:
        status = result.status
        execution_status = status if status in _TERMINAL - {"pending"} else "failed"
        error_override = None
        if status == "denied":
            error_override = "Command was denied by the Sandbox permission policy."
        elif status == "approval_required":
            error_override = "Command requires approval and was not executed."
            self.record_stage(
                sandbox_id,
                "approval",
                "complete",
                "Approval requested; awaiting a user decision.",
            )
        elif status == "failed":
            error_override = (
                f"Command exited with code {result.exit_code}."
                if result.exit_code is not None
                else "Command execution failed."
            )
        command_result = SandboxExecutionResult(
            sandbox_id=sandbox_id,
            status=execution_status,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            output_limit_exceeded=result.output_limit_exceeded,
            oom_killed=result.oom_killed,
            runtime=result.runtime,
            image=result.image,
            workspace_changeset=result.workspace_changeset,
            output_files=result.output_files,
            runtime_info=result.runtime_info,
        )
        return self._finish_result(
            sandbox_id, command_result, error_override=error_override
        )

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
            self._set_run_status(sandbox_id, "preparing")
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
                                _safe_debug_file(item)
                                for item in snapshot.manifest
                            ],
                        }
                    )
                for item in snapshot.manifest:
                    self._add_activity(
                        sandbox_id,
                        kind="file",
                        action="filesystem.read",
                        target=_safe_trace_relative_path(item.get("relative_path", "")),
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
            if entry.command is not None:
                from backend.sandbox.command_runtime import SandboxCommandExecutor
                from backend.models.sandbox_permissions import ExecutionPolicy
                result = SandboxCommandExecutor(manager).execute(entry.command,
                    execution_policy=ExecutionPolicy(profile="read_only", workspace_id=filesystem_workspace_id),
                    input_files=input_files, sandbox_id=sandbox_id,
                    on_stage=lambda key, status, note: self._set_stage(sandbox_id, key, status, note),
                    on_activity=lambda **activity: self.record_activity(sandbox_id, **activity),
                    on_observation=lambda event: self.record_observation(sandbox_id, event), cancel_event=entry.cancel_event)
                self.finish_command_run(sandbox_id, result)
                return
            result = manager.execute_python(
                code,
                input_files=input_files,
                sandbox_id=sandbox_id,
                on_stage=lambda key, status, note: self._set_stage(
                    sandbox_id, key, status, note
                ),
                cancel_event=entry.cancel_event,
                on_observation=lambda event: self.record_observation(sandbox_id, event),
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
            self._persist_locked(entry)
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
            if entry is None or entry.trace.run.status in _TERMINAL or (entry.cancel_event.is_set() and status != "cancelling"):
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
                stage.model_copy(
                    update={
                        "status": status,
                        "elapsed_ms": elapsed,
                        "note": _safe_trace_text(note, limit=1024),
                    }
                )
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
        permission_action: str = "",
        policy_rule: str = "",
        approval_id: str = "",
        grant_id: str = "",
    ) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                return
            self._append_activity_locked(
                entry,
                kind=kind,
                action=action,
                target=target,
                decision=decision,
                reason=reason,
                permission_action=permission_action,
                policy_rule=policy_rule,
                approval_id=approval_id,
                grant_id=grant_id,
            )

    def record_activity(
        self,
        sandbox_id: str,
        *,
        kind: str,
        action: str,
        target: str = "",
        decision: str,
        reason: str = "",
        permission_action: str = "",
        policy_rule: str = "",
        approval_id: str = "",
        grant_id: str = "",
    ) -> None:
        """Append a bounded, scrubbed event from another sandbox service."""
        self._add_activity(
            sandbox_id,
            kind=kind,
            action=action,
            target=target,
            decision=decision,
            reason=reason,
            permission_action=permission_action,
            policy_rule=policy_rule,
            approval_id=approval_id,
            grant_id=grant_id,
        )

    def record_stage(self, sandbox_id: str, key: str, status: str, note: str = "") -> None:
        """Expose lifecycle stage updates to command and apply services."""
        self._set_stage(sandbox_id, key, status, note)

    def observation_callback(self, sandbox_id: str) -> Callable[[dict], None]:
        return lambda event: self.record_observation(sandbox_id, event)

    def record_observation(self, sandbox_id: str, event: dict) -> None:
        """Observations never grant permissions; publish bounded, scrubbed state."""
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None or entry.trace.run.status in _TERMINAL:
                return
            kind = event.get("type")
            if kind == "output":
                secrets = self._secret_values_provider()
                updates = {}
                for channel in ("stdout", "stderr"):
                    value = str(event.get(channel, ""))[:1_048_576]
                    # Cumulative output can end halfway through a secret. Withhold
                    # that suffix until another frame or the final result arrives.
                    withheld = 0
                    for secret in secrets:
                        for length in range(1, min(len(value), len(secret) - 1) + 1):
                            if value.endswith(secret[:length]):
                                withheld = max(withheld, length)
                    if withheld:
                        value = value[:-withheld]
                    updates[channel] = _safe_trace_text(value, limit=1_048_576, secret_values=secrets)
                entry.trace = entry.trace.model_copy(update=updates)
                self._record_event_locked(entry, {"type": "output", **updates})
            elif kind == "disk":
                entry.disk_usage = {key: max(0, int(event.get(key, 0))) for key in entry.disk_usage}
            elif kind == "resource":
                sample = SandboxResourceSample.model_validate({**event.get("sample", {}), **entry.disk_usage})
                entry.trace = entry.trace.model_copy(update={"resources": [*entry.trace.resources[-239:], sample]})
                self._record_event_locked(entry, {"type": "resource", "sample": sample.model_dump(mode="json")})
            elif kind == "policy":
                values = {key: value for key, value in event.get("policy", event).items() if key in SandboxEffectivePolicy.model_fields}
                policy = SandboxEffectivePolicy.model_validate({**entry.trace.policy.model_dump(), **values})
                entry.trace = entry.trace.model_copy(update={"policy": policy, "runtime_info": event.get("runtime_info", {})})
                self._record_event_locked(entry, {"type": "trace"})

    def record_input_files(
        self,
        sandbox_id: str,
        manifest: tuple[dict[str, object], ...],
    ) -> None:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                return
            entry.trace = entry.trace.model_copy(
                update={"input_files": [_safe_debug_file(item) for item in manifest]}
            )
            self._record_event_locked(
                entry,
                {"type": "trace", "trace": entry.trace.model_dump(mode="json")},
            )

    def record_activity_for_context(
        self,
        run_id: str,
        tool_call_id: str,
        **activity: str,
    ) -> str | None:
        """Attach an approval event to the trace for its original tool request."""
        with self._condition:
            sandbox_id = next(
                (
                    key
                    for key, entry in reversed(self._runs.items())
                    if entry.trace.run.run_id == run_id
                    and entry.trace.run.tool_call_id == tool_call_id
                ),
                None,
            )
        if sandbox_id is None:
            return None
        self.record_activity(sandbox_id, **activity)
        return sandbox_id

    def record_stage_for_context(
        self,
        run_id: str,
        tool_call_id: str,
        key: str,
        status: str,
        note: str = "",
    ) -> None:
        with self._condition:
            sandbox_id = next(
                (
                    sandbox_id
                    for sandbox_id, entry in reversed(self._runs.items())
                    if entry.trace.run.run_id == run_id
                    and entry.trace.run.tool_call_id == tool_call_id
                ),
                None,
            )
        if sandbox_id is not None:
            self.record_stage(sandbox_id, key, status, note)

    def _append_activity_locked(
        self,
        entry: _RunEntry,
        *,
        kind: str,
        action: str,
        target: str,
        decision: str,
        reason: str,
        permission_action: str = "",
        policy_rule: str = "",
        approval_id: str = "",
        grant_id: str = "",
    ) -> None:
        activity = SandboxActivityEvent(
            sequence=entry.trace.activities[-1].sequence + 1 if entry.trace.activities else 0,
            timestamp=self._now(),
            kind=kind,
            action=_safe_trace_text(action, limit=128),
            target=_safe_trace_target(target),
            decision=decision,
            reason=_safe_trace_text(reason, limit=1024),
            permission_action=_safe_trace_text(permission_action, limit=128),
            policy_rule=_safe_trace_text(policy_rule, limit=128),
            approval_id=_safe_trace_text(approval_id, limit=128),
            grant_id=_safe_trace_text(grant_id, limit=128),
        )
        entry.trace = entry.trace.model_copy(
            update={"activities": [*entry.trace.activities[-499:], activity]}
        )
        self._record_event_locked(
            entry,
            {"type": "activity", "activity": activity.model_dump(mode="json")},
        )

    def _finish_result(
        self,
        sandbox_id: str,
        result: SandboxExecutionResult,
        *,
        error_override: str | None = None,
    ) -> SandboxDebugTrace:
        with self._condition:
            entry = self._runs.get(sandbox_id)
            if entry is None:
                raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            now = self._now()
            status = result.status
            known_secrets = self._secret_values_provider()
            workspace_changes = [
                SandboxDebugWorkspaceChange(
                    operation=change.operation,
                    path=change.path,
                    before_sha256=change.before_sha256,
                    after_sha256=change.after_sha256,
                    size_before=change.size_before,
                    size_after=change.size_after,
                    size_delta=(change.size_after or 0) - (change.size_before or 0),
                )
                for change in (
                    result.workspace_changeset.changes
                    if result.workspace_changeset is not None
                    else ()
                )
            ]
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
                    "stdout": _safe_trace_text(
                        result.stdout,
                        limit=max(1, len(result.stdout)),
                        secret_values=known_secrets,
                    ),
                    "stderr": _safe_trace_text(
                        result.stderr,
                        limit=max(1, len(result.stderr)),
                        secret_values=known_secrets,
                    ),
                    "output_files": [
                        SandboxDebugFile(
                            file_id=item.file_id,
                            relative_path=_safe_trace_relative_path(item.relative_path),
                            size_bytes=item.size_bytes,
                            sha256=item.sha256,
                            source="generated",
                        )
                        for item in result.output_files
                    ],
                    "workspace_changes": workspace_changes,
                    "runtime_info": result.runtime_info or entry.trace.runtime_info,
                    "error": (
                        error_override
                        if error_override is not None
                        else self._result_message(result)
                    ),
                }
            )
            for change in workspace_changes:
                self._append_activity_locked(
                    entry,
                    kind="file",
                    action="filesystem.change",
                    target=change.path,
                    decision="observed",
                    reason=f"Sandbox {change.operation} change recorded.",
                    policy_rule="workspace_write.sandbox_diff",
                )
            self._complete_remaining_stages(entry, status)
            final_sample = SandboxResourceSample(timestamp_ms=result.duration_ms, stdout_bytes=result.stdout_bytes,
                stderr_bytes=result.stderr_bytes, **entry.disk_usage)
            entry.trace = entry.trace.model_copy(update={"resources": [*entry.trace.resources[-239:], final_sample]})
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
            message = _safe_trace_text(
                str(error).strip() or type(error).__name__,
                limit=1000,
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
        if result.status == "storage_limit_exceeded":
            return "Execution exceeded the workspace or output storage limit."
        if result.status == "oom_killed":
            return "Python execution exceeded the memory limit."
        if result.status == "cancelled":
            return "Python execution was cancelled."
        if result.status == "failed":
            return f"Python execution exited with code {result.exit_code}." if result.exit_code is not None else "Python execution failed."
        return ""

    def _record_event_locked(self, entry: _RunEntry, event: dict[str, Any]) -> None:
        entry.trace = entry.trace.model_copy(update={"sequence": entry.trace.sequence + 1})
        event = {**event, "sequence": entry.trace.sequence}
        if event["type"] in {"trace", "terminal"}:
            event["trace"] = entry.trace.model_dump(mode="json")
        entry.events.append(event)
        entry.event_sizes.append(len(json.dumps(event, ensure_ascii=False).encode("utf-8")))
        while len(entry.events) > 1 and (len(entry.events) > 2048 or sum(entry.event_sizes) > 8 * 1024 * 1024):
            entry.events.pop(0)
            entry.event_sizes.pop(0)
        entry.event_base = entry.trace.sequence - len(entry.events)
        if event["type"] in {"trace", "terminal"} or monotonic() - entry.last_persist >= 1:
            self._persist_locked(entry)
        self._condition.notify_all()

    def _persist_locked(self, entry: _RunEntry) -> None:
        if self._store:
            self._store.save(entry.trace, entry.owner, terminal=entry.trace.run.status in _TERMINAL)
        entry.last_persist = monotonic()

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
            if not entry.owned:
                raise SandboxDebugError("foreign_run", "This run belongs to another backend process.", status_code=409)
            entry.cancel_event.set()
            future = entry.future
        self._set_run_status(sandbox_id, "cancelling")
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
            if after_index >= entry.trace.sequence and entry.trace.run.status not in _TERMINAL:
                self._condition.wait(timeout=max(0.0, timeout))
                entry = self._runs.get(sandbox_id)
                if entry is None:
                    raise SandboxDebugError("run_not_found", "Sandbox run not found.", status_code=404)
            if after_index < entry.event_base:
                events = [{"type": "terminal" if entry.trace.run.status in _TERMINAL else "trace", "sequence": entry.trace.sequence, "trace": entry.trace.model_dump(mode="json")}]
            else:
                events = entry.events[max(0, after_index - entry.event_base):]
            complete = entry.trace.run.status in _TERMINAL
            return [dict(event) for event in events], complete

    async def stream(self, websocket: Any, sandbox_id: str) -> None:
        await websocket.accept()
        trace = self.get_run(sandbox_id)
        cursor = trace.sequence
        try:
            await websocket.send_json({"type": "terminal" if trace.run.status in _TERMINAL else "trace", "sequence": cursor, "trace": trace.model_dump(mode="json")})
            if trace.run.status in _TERMINAL:
                return
            while True:
                events, complete = await asyncio.to_thread(
                    self.wait_events,
                    sandbox_id,
                    cursor,
                    timeout=0.5,
                )
                for event in events:
                    await websocket.send_json(event)
                    cursor = event["sequence"]
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
                if entry.owned and entry.trace.run.status not in _TERMINAL:
                    entry.cancel_event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        for entry in entries:
            if entry.owned and entry.trace.run.status not in _TERMINAL:
                self._finish_cancelled(entry.trace.run.sandbox_id)


__all__ = ["SandboxDebugError", "SandboxDebugService"]


def _safe_trace_text(
    value: object,
    *,
    limit: int,
    secret_values: tuple[str, ...] | None = None,
) -> str:
    text = str(value or "")
    text = _WINDOWS_ABSOLUTE_PATH.sub("[host path redacted]", text)
    text = re.sub(
        r"(?<![/:\\\w])/(?!/)[^\s\"'<>|,;]+",
        lambda match: match.group(0)
        if match.group(0) == "/input"
        or match.group(0).startswith("/input/")
        or match.group(0) == "/workspace"
        or match.group(0).startswith("/workspace/")
        else "[host path redacted]",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = redact_known_secret_values(
        text,
        secret_values=(
            secret_values
            if secret_values is not None
            else known_secret_environment_values()
        ),
    )
    return text[:limit]


def _safe_trace_target(value: object) -> str:
    target = str(value or "").strip()
    if _WINDOWS_ABSOLUTE_PATH.search(target):
        return "[host path redacted]"
    if target.startswith("/") and not (
        target in _SAFE_CONTAINER_PATHS
        or target.startswith(("/input/", "/workspace/"))
    ):
        return "[host path redacted]"
    if not target.startswith("/") and "/" in target:
        return _safe_trace_relative_path(target)
    if ".." in target.split("\\") or ".." in target.split("/"):
        return "[host path redacted]"
    return _safe_trace_text(target, limit=1024)


def _safe_trace_relative_path(value: object) -> str:
    path = str(value or "").replace("\\", "/")
    if (
        not path
        or path.startswith("/")
        or _WINDOWS_ABSOLUTE_PATH.search(path)
        or ":" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        return "[path redacted]"
    return _safe_trace_text(path, limit=1024)


def _safe_debug_file(item: object) -> SandboxDebugFile:
    if hasattr(item, "model_dump"):
        data = item.model_dump()
    else:
        data = dict(item)  # type: ignore[arg-type]
    data["relative_path"] = _safe_trace_relative_path(data.get("relative_path", ""))
    return SandboxDebugFile.model_validate(data)
