"""Service-level P0 flow tests with a deterministic in-process sandbox runtime.

Docker isolation itself is covered by the docker_integration test modules. These
tests connect the Agent command tool, workspace snapshot/change capture, approval,
single-use apply, and debug trace without requiring a Docker daemon.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.workspace import SandboxWorkspace, SandboxWorkspaceManager
from backend.sandbox.workspace_snapshot import WorkspaceChangeSet
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.filesystem_workspace_service import (
    FilesystemWorkspaceService,
)
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.sandbox_debug_service import SandboxDebugService
from backend.services.workspace_apply_service import (
    WorkspaceApplyError,
    WorkspaceApplyService,
)


class DeterministicRuntime:
    image = "aitrans-python-sandbox:p0-e2e"
    policy = DEFAULT_SANDBOX_POLICY

    def __init__(self, *, edit_workspace: bool) -> None:
        self.edit_workspace = edit_workspace
        self.requests: list[SandboxExecutionRequest] = []

    def execute_python(
        self,
        request: SandboxExecutionRequest,
        *,
        workspace: SandboxWorkspace,
        on_stage=None,
        cancel_event=None,
    ) -> SandboxExecutionResult:
        self.requests.append(request)
        if request.network_policy.mode != "none":
            raise AssertionError("the default sandbox network policy must be none")
        source = workspace.input_dir / "src" / "main.py"
        assert source.read_text(encoding="utf-8") == "print('before')\n"
        assert stat.S_IMODE(source.stat().st_mode) & 0o222 == 0

        if self.edit_workspace:
            editable = workspace.workspace_dir / "src" / "main.py"
            editable.write_text("print('after')\n", encoding="utf-8")
            (workspace.workspace_dir / "src" / "new.py").write_text(
                "print('new')\n", encoding="utf-8"
            )

        return SandboxExecutionResult(
            sandbox_id=request.sandbox_id,
            status="succeeded",
            exit_code=0,
            stdout="2 passed\n",
            duration_ms=12,
            stdout_bytes=9,
            image=self.image,
        )


def _record_approval_transition(
    debug_service: SandboxDebugService,
    approval,
    transition: str,
    grant_id: str,
) -> None:
    target = (
        approval.requested_changes[0].path
        if approval.requested_changes
        else approval.target
    )
    sandbox_id = debug_service.record_activity_for_context(
        approval.run_id,
        approval.tool_call_id,
        kind="approval",
        action=f"approval.{transition}",
        target=target,
        decision=approval.status,
        reason=approval.reason,
        permission_action=approval.permission_action,
        policy_rule=approval.permission_action,
        approval_id=approval.approval_id,
        grant_id=grant_id,
    )
    if sandbox_id:
        debug_service.record_stage(
            sandbox_id,
            "approval",
            "running" if transition == "created" else "complete",
            f"Approval {approval.status}.",
        )


def _services(tmp_path: Path, *, edit_workspace: bool):
    selected = tmp_path / "selected"
    (selected / "src").mkdir(parents=True)
    original = selected / "src" / "main.py"
    original.write_text("print('before')\n", encoding="utf-8")

    workspaces = FilesystemWorkspaceService(tmp_path / "filesystem.sqlite3")
    workspace = workspaces.create(str(selected))
    debug_service = SandboxDebugService()
    approvals = SandboxApprovalService(
        transition_recorder=lambda approval, transition, grant_id: (
            _record_approval_transition(
                debug_service, approval, transition, grant_id
            )
        )
    )
    artifacts = tmp_path / "artifacts"
    runtime = DeterministicRuntime(edit_workspace=edit_workspace)
    manager = SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=tmp_path / "sandboxes",
            artifact_root=artifacts,
        ),
    )
    registry = AgentToolRegistry(
        sandbox_manager=manager,
        filesystem_workspace_service=workspaces,
        sandbox_debug_service=debug_service,
    )
    apply_service = WorkspaceApplyService(
        workspaces,
        approvals,
        change_store_root=artifacts / "workspace_changes",
        audit_database_path=tmp_path / "workspace-audit.sqlite3",
        debug_service=debug_service,
    )
    return (
        selected,
        original,
        workspaces,
        workspace,
        debug_service,
        approvals,
        registry,
        apply_service,
        runtime,
    )


@pytest.fixture
def service_cleanup():
    services: list[SandboxDebugService] = []
    yield services
    for service in services:
        service.close()


def test_p0_read_only_command_has_no_approval_or_host_changes(
    tmp_path: Path,
    service_cleanup: list[SandboxDebugService],
) -> None:
    (
        _selected,
        original,
        _workspaces,
        workspace,
        debug_service,
        _approvals,
        registry,
        _apply_service,
        runtime,
    ) = _services(tmp_path, edit_workspace=False)
    service_cleanup.append(debug_service)

    result = registry.execute(
        "command_execute",
        argv=["python", "-m", "pytest", "-q"],
        filesystem_workspace_id=workspace.workspace_id,
        run_id="run-p0-read-only",
        tool_call_id="call-p0-read-only",
    )

    trace = debug_service.get_run(result.data["sandbox_id"])
    actions = [activity.action for activity in trace.activities]
    assert result.data["status"] == "succeeded"
    assert runtime.requests
    assert original.read_text(encoding="utf-8") == "print('before')\n"
    assert trace.workspace_changes == []
    assert "filesystem.read" in actions
    assert "command.start" in actions
    assert "command.exit" in actions
    assert not any(action.startswith("approval.") for action in actions)


def test_p0_agent_change_requires_approval_then_applies_once_and_traces(
    tmp_path: Path,
    service_cleanup: list[SandboxDebugService],
) -> None:
    (
        selected,
        original,
        _workspaces,
        workspace,
        debug_service,
        approvals,
        registry,
        apply_service,
        _runtime,
    ) = _services(tmp_path, edit_workspace=True)
    service_cleanup.append(debug_service)

    result = registry.execute(
        "command_execute",
        argv=["python", "-m", "pytest", "-q"],
        filesystem_workspace_id=workspace.workspace_id,
        run_id="run-p0-edit",
        tool_call_id="call-p0-edit",
    )
    changeset = result.data["workspace_changeset"]
    paths = {change["path"] for change in changeset["changes"]}

    assert result.data["status"] == "succeeded"
    assert paths == {"src/main.py", "src/new.py"}
    assert original.read_text(encoding="utf-8") == "print('before')\n"
    assert not (selected / "src" / "new.py").exists()

    changeset_model = WorkspaceChangeSet.model_validate(changeset)
    trace = debug_service.get_run(result.data["sandbox_id"])
    approval = apply_service.request_approval(changeset_model)
    assert approval.status == "pending"
    assert approvals.list_pending()[0].approval_id == approval.approval_id

    trace = debug_service.get_run(result.data["sandbox_id"])
    assert {change.path for change in trace.workspace_changes} == paths
    assert "approval.created" in [activity.action for activity in trace.activities]
    assert original.read_text(encoding="utf-8") == "print('before')\n"

    approvals.approve(approval.approval_id)
    applied = apply_service.apply(changeset_model, approval_id=approval.approval_id)

    assert applied.status == "applied"
    assert original.read_text(encoding="utf-8") == "print('after')\n"
    assert (selected / "src" / "new.py").read_text(encoding="utf-8") == "print('new')\n"
    assert approvals.get(approval.approval_id).status == "consumed"
    applied_trace = debug_service.get_run(result.data["sandbox_id"])
    assert next(
        stage for stage in applied_trace.stages if stage.key == "apply"
    ).status == "complete"
    assert "approval.consumed" in [
        activity.action for activity in applied_trace.activities
    ]

    with pytest.raises(WorkspaceApplyError) as replay:
        apply_service.apply(changeset_model, approval_id=approval.approval_id)
    assert replay.value.code == "approval_grant_replayed"
    assert original.read_text(encoding="utf-8") == "print('after')\n"

    trace = debug_service.get_run(result.data["sandbox_id"])
    actions = [activity.action for activity in trace.activities]
    assert "approval.approved" in actions
    assert "approval.consumed" in actions
    assert "filesystem.apply" in actions
    assert "permission.approval_required" in actions
    assert next(stage for stage in trace.stages if stage.key == "apply").status == "failed"
    assert any(
        activity.decision == "denied"
        for activity in trace.activities
        if activity.action == "filesystem.apply"
    )


def test_p0_denied_workspace_apply_keeps_host_unchanged(
    tmp_path: Path,
    service_cleanup: list[SandboxDebugService],
) -> None:
    (
        _selected,
        original,
        _workspaces,
        workspace,
        debug_service,
        approvals,
        registry,
        apply_service,
        _runtime,
    ) = _services(tmp_path, edit_workspace=True)
    service_cleanup.append(debug_service)

    result = registry.execute(
        "command_execute",
        argv=["python", "-m", "pytest", "-q"],
        filesystem_workspace_id=workspace.workspace_id,
        run_id="run-p0-deny",
        tool_call_id="call-p0-deny",
    )
    changeset = WorkspaceChangeSet.model_validate(result.data["workspace_changeset"])
    approval = apply_service.request_approval(changeset)
    approvals.deny(approval.approval_id)

    with pytest.raises(WorkspaceApplyError) as denied:
        apply_service.apply(changeset, approval_id=approval.approval_id)

    assert denied.value.code == "approval_not_approved"
    assert original.read_text(encoding="utf-8") == "print('before')\n"
    assert not (original.parent / "new.py").exists()
    trace = debug_service.get_run(result.data["sandbox_id"])
    actions = [activity.action for activity in trace.activities]
    assert "approval.denied" in actions
    assert any(
        activity.action == "filesystem.apply" and activity.decision == "denied"
        for activity in trace.activities
    )
