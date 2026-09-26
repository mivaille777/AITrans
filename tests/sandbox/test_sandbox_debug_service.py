from __future__ import annotations

import time

from backend.sandbox.models import SandboxExecutionResult, SandboxOutputFile
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.workspace_snapshot import (
    create_workspace_changeset,
    create_workspace_snapshot,
)
from backend.services.sandbox_debug_service import SandboxDebugService


class FakeManager:
    image = "aitrans-python-sandbox:v1"
    policy = DEFAULT_SANDBOX_POLICY

    def execute_python(self, code: str, **kwargs) -> SandboxExecutionResult:
        assert code
        emit = kwargs.get("on_stage")
        for stage in (
            "staging",
            "create",
            "start",
            "execute",
            "collect",
            "cleanup",
        ):
            emit(stage, "running", f"{stage} started")
            emit(stage, "complete", f"{stage} completed")
        return SandboxExecutionResult(
            sandbox_id=kwargs["sandbox_id"],
            status="succeeded",
            exit_code=0,
            stdout="42\n",
            stdout_bytes=3,
            duration_ms=9,
            image=self.image,
            output_files=[
                SandboxOutputFile(
                    file_id="sbo_result",
                    relative_path="result.txt",
                    size_bytes=2,
                    sha256="a" * 64,
                )
            ],
        )

    def cancel(self, sandbox_id: str) -> bool:
        return True


def _wait_for_terminal(service: SandboxDebugService, sandbox_id: str):
    for _ in range(200):
        trace = service.get_run(sandbox_id)
        if trace.run.status in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
            "oom_killed",
            "output_limit_exceeded",
        }:
            return trace
        time.sleep(0.01)
    raise AssertionError("Sandbox debug run did not reach a terminal state")


def test_manual_run_records_trace_and_emits_terminal_event() -> None:
    service = SandboxDebugService()
    try:
        accepted = service.start_manual_run(
            code="print(6 * 7)",
            filesystem_workspace_id="",
            manager=FakeManager(),
            workspace_service=None,
        )
        trace = _wait_for_terminal(service, accepted.sandbox_id)
        events, complete = service.wait_events(accepted.sandbox_id, 0, timeout=0)

        assert trace.run.source == "manual"
        assert trace.run.status == "succeeded"
        assert trace.stdout == "42\n"
        assert trace.output_files[0].relative_path == "result.txt"
        assert [stage.key for stage in trace.stages] == [
            "request",
            "permission",
            "approval",
            "workspace",
            "staging",
            "create",
            "start",
            "execute",
            "network",
            "changes",
            "apply",
            "collect",
            "cleanup",
        ]
        assert trace.stages[0].status == "complete"
        assert trace.stages[1].status == "complete"
        assert trace.stages[2].status == "skipped"
        assert trace.stages[-1].status == "complete"
        assert events[-1]["type"] == "terminal"
        assert complete is True
        assert service.list_runs()[0].sandbox_id == accepted.sandbox_id
    finally:
        service.close()


def test_agent_run_can_be_opened_in_debug_history() -> None:
    service = SandboxDebugService()
    try:
        manifest = (
            {
                "file_id": "fsw_file",
                "relative_path": "data.csv",
                "size_bytes": 3,
                "sha256": "b" * 64,
                "source": "workspace",
            },
        )
        sandbox_id, on_stage = service.begin_agent_run(
            run_id="agent-run-1",
            tool_call_id="tool-call-1",
            filesystem_workspace_id="fsw_workspace",
            workspace_name="selected-folder",
            input_manifest=manifest,
            manager=FakeManager(),
        )
        on_stage("staging", "complete", "Input staged.")
        trace = service.finish_agent_run(
            sandbox_id,
            SandboxExecutionResult(
                sandbox_id=sandbox_id,
                status="succeeded",
                exit_code=0,
                stdout="loaded\n",
                duration_ms=11,
                image=FakeManager.image,
            ),
        )

        assert trace.run.source == "agent"
        assert trace.run.run_id == "agent-run-1"
        assert trace.run.tool_call_id == "tool-call-1"
        assert trace.run.workspace_id == "fsw_workspace"
        assert trace.input_files[0].relative_path == "data.csv"
        read_event = next(
            activity
            for activity in trace.activities
            if activity.action == "filesystem.read"
        )
        assert read_event.target == "data.csv"
        assert trace.activities[0].action == "permission.request"
    finally:
        service.close()


def test_agent_trace_records_workspace_diff_without_host_paths() -> None:
    service = SandboxDebugService()
    try:
        sandbox_id, _on_stage = service.begin_agent_run(
            run_id="agent-run-diff",
            tool_call_id="tool-call-diff",
            manager=FakeManager(),
        )
        base = create_workspace_snapshot(
            "fsw_workspace",
            [
                {
                    "relative_path": "src/main.py",
                    "sha256": "a" * 64,
                    "size": 10,
                    "mode": 0o644,
                }
            ],
        )
        current = create_workspace_snapshot(
            "fsw_workspace",
            [
                {
                    "relative_path": "src/main.py",
                    "sha256": "b" * 64,
                    "size": 15,
                    "mode": 0o644,
                },
                {
                    "relative_path": "tests/test_main.py",
                    "sha256": "c" * 64,
                    "size": 4,
                    "mode": 0o644,
                },
            ],
        )
        changeset = create_workspace_changeset(
            base, current, sandbox_id=sandbox_id
        )

        trace = service.finish_agent_run(
            sandbox_id,
            SandboxExecutionResult(
                sandbox_id=sandbox_id,
                status="succeeded",
                duration_ms=8,
                workspace_changeset=changeset,
            ),
        )

        assert [(change.operation, change.path) for change in trace.workspace_changes] == [
            ("modify", "src/main.py"),
            ("create", "tests/test_main.py"),
        ]
        assert trace.workspace_changes[0].size_delta == 5
        assert trace.workspace_changes[0].before_sha256 == "a" * 64
        assert trace.workspace_changes[0].after_sha256 == "b" * 64
        assert all(activity.action == "filesystem.change" for activity in trace.activities[-2:])
        assert "D:\\private\\project" not in str(trace.model_dump(mode="json"))
    finally:
        service.close()


def test_activity_redacts_host_paths_and_credentials() -> None:
    service = SandboxDebugService()
    try:
        sandbox_id, _on_stage = service.begin_agent_run(
            run_id="agent-run-redaction",
            tool_call_id="tool-call-redaction",
            manager=FakeManager(),
        )
        service.record_activity(
            sandbox_id,
            kind="policy",
            action="permission.deny",
            target=r"C:\Users\huaqi\project\secret.py",
            decision="denied",
            reason="token=secret-value at /private/host/project",
        )

        trace = service.get_run(sandbox_id)
        recorded = trace.activities[-1]
        assert recorded.target == "[host path redacted]"
        assert "secret-value" not in recorded.reason
        assert "C:\\Users" not in recorded.target
        assert "/private/host" not in recorded.reason
    finally:
        service.close()


def test_debug_trace_redacts_known_secret_values_from_both_output_streams(
    monkeypatch,
) -> None:
    secret = "DO_NOT_LEAK_TRACE_VALUE"
    monkeypatch.setenv("AITRANS_TEST_SECRET", secret)
    service = SandboxDebugService()
    try:
        sandbox_id, _on_stage = service.begin_agent_run(
            run_id="agent-run-secret",
            tool_call_id="tool-call-secret",
            manager=FakeManager(),
        )
        trace = service.finish_agent_run(
            sandbox_id,
            SandboxExecutionResult(
                sandbox_id=sandbox_id,
                status="failed",
                exit_code=1,
                stdout=f"stdout={secret}",
                stderr=f"stderr={secret}",
                duration_ms=12,
                image=FakeManager.image,
            ),
        )
        events, complete = service.wait_events(sandbox_id, 0, timeout=0)

        assert trace.stdout == "stdout=[REDACTED]"
        assert trace.stderr == "stderr=[REDACTED]"
        assert secret not in str(trace.model_dump(mode="json"))
        assert secret not in str(events)
        assert events[-1]["type"] == "terminal"
        assert complete is True
    finally:
        service.close()
