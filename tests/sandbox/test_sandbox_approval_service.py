from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.models.sandbox_permissions import ExecutionPolicy, PermissionRequest
from backend.sandbox.permissions import PermissionPolicyEngine
from backend.services.sandbox_approval_service import (
    SandboxApprovalError,
    SandboxApprovalService,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _approval_context(target: str = "src/a.py"):
    request = PermissionRequest(
        action="filesystem.apply_host",
        target=target,
        reason="Apply the reviewed sandbox changes.",
        tool_name="workspace_apply",
        run_id="run-1",
        tool_call_id="call-1",
    )
    policy = ExecutionPolicy(profile="workspace_write", workspace_id="workspace-1")
    decision = PermissionPolicyEngine().evaluate(request, policy)
    assert decision.decision == "approval_required"
    return request, decision


def _approved_service(*, clock=None) -> tuple[SandboxApprovalService, str, dict]:
    service = SandboxApprovalService(clock=clock)
    request, decision = _approval_context()
    approval = service.create_approval(request, decision)
    service.approve(approval.approval_id)
    return service, approval.approval_id, decision.granted_scope


def test_create_and_approve_creates_run_bound_single_use_grant() -> None:
    service = SandboxApprovalService()
    request, decision = _approval_context()
    approval = service.create_approval(request, decision)

    assert approval.status == "pending"
    assert approval.permission_action == "filesystem.apply_host"
    assert approval.target == "src/a.py"
    assert approval.run_id == "run-1"
    assert approval.tool_call_id == "call-1"

    approved = service.approve(approval.approval_id)
    grant = service.consume_grant(
        approval.approval_id,
        action="filesystem.apply_host",
        scope=decision.granted_scope,
        run_id="run-1",
        tool_call_id="call-1",
    )

    assert approved.status == "approved"
    assert grant.approval_id == approval.approval_id
    assert grant.action == "filesystem.apply_host"
    assert grant.scope == decision.granted_scope
    assert grant.single_use is True
    assert service.get(approval.approval_id).status == "consumed"


def test_deny_never_creates_a_usable_grant() -> None:
    service = SandboxApprovalService()
    request, decision = _approval_context()
    approval = service.create_approval(request, decision)

    denied = service.deny(approval.approval_id)

    assert denied.status == "denied"
    with pytest.raises(SandboxApprovalError, match="does not have an active grant"):
        service.consume_grant(
            approval.approval_id,
            action="filesystem.apply_host",
            scope=decision.granted_scope,
            run_id="run-1",
            tool_call_id="call-1",
        )


def test_expired_approval_is_removed_from_pending_and_cannot_be_approved() -> None:
    clock = MutableClock()
    service = SandboxApprovalService(ttl_seconds=5, clock=clock)
    request, decision = _approval_context()
    approval = service.create_approval(request, decision)
    clock.value += timedelta(seconds=6)

    assert service.list_pending() == []
    assert service.get(approval.approval_id).status == "expired"
    with pytest.raises(SandboxApprovalError, match="has expired"):
        service.approve(approval.approval_id)


def test_grant_can_only_be_consumed_once() -> None:
    service, approval_id, scope = _approved_service()
    arguments = {
        "action": "filesystem.apply_host",
        "scope": scope,
        "run_id": "run-1",
        "tool_call_id": "call-1",
    }

    service.consume_grant(approval_id, **arguments)
    with pytest.raises(SandboxApprovalError, match="already been consumed"):
        service.consume_grant(approval_id, **arguments)


def test_grant_is_bound_to_the_approving_run() -> None:
    service, approval_id, scope = _approved_service()

    with pytest.raises(SandboxApprovalError, match="does not match"):
        service.consume_grant(
            approval_id,
            action="filesystem.apply_host",
            scope=scope,
            run_id="run-2",
            tool_call_id="call-1",
        )


def test_grant_is_bound_to_the_approving_tool_call() -> None:
    service, approval_id, scope = _approved_service()

    with pytest.raises(SandboxApprovalError, match="does not match"):
        service.consume_grant(
            approval_id,
            action="filesystem.apply_host",
            scope=scope,
            run_id="run-1",
            tool_call_id="call-2",
        )


def test_grant_scope_cannot_be_replayed_for_a_different_file() -> None:
    service, approval_id, scope = _approved_service()
    other_target_scope = {**scope, "target": "src/b.py"}

    with pytest.raises(SandboxApprovalError, match="does not match"):
        service.consume_grant(
            approval_id,
            action="filesystem.apply_host",
            scope=other_target_scope,
            run_id="run-1",
            tool_call_id="call-1",
        )

    # A failed mismatched attempt does not broaden or consume the original grant.
    grant = service.consume_grant(
        approval_id,
        action="filesystem.apply_host",
        scope=scope,
        run_id="run-1",
        tool_call_id="call-1",
    )
    assert grant.scope["target"] == "src/a.py"


def test_grant_expiry_revokes_an_already_approved_request() -> None:
    clock = MutableClock()
    service = SandboxApprovalService(ttl_seconds=5, clock=clock)
    request, decision = _approval_context()
    approval = service.create_approval(request, decision)
    service.approve(approval.approval_id)
    clock.value += timedelta(seconds=6)

    with pytest.raises(SandboxApprovalError, match="has expired"):
        service.consume_grant(
            approval.approval_id,
            action="filesystem.apply_host",
            scope=decision.granted_scope,
            run_id="run-1",
            tool_call_id="call-1",
        )
    assert service.get(approval.approval_id).status == "expired"


def test_service_rejects_requests_without_policy_approval() -> None:
    service = SandboxApprovalService()
    request, _decision = _approval_context()
    from backend.models.sandbox_permissions import PermissionDecision

    with pytest.raises(SandboxApprovalError, match="Only policy decisions"):
        service.create_approval(
            request,
            PermissionDecision(
                decision="allow",
                reason_code="policy.allowed",
                reason="No approval needed.",
            ),
        )


def test_approval_must_be_bound_to_run_and_tool_call() -> None:
    service = SandboxApprovalService()
    request, decision = _approval_context()
    unbound = request.model_copy(update={"tool_call_id": ""})

    with pytest.raises(SandboxApprovalError, match="bound to a run and tool call"):
        service.create_approval(unbound, decision)


def test_approval_request_scope_must_match_policy_decision() -> None:
    service = SandboxApprovalService()
    request, decision = _approval_context()
    different_target = request.model_copy(update={"target": "src/b.py"})

    with pytest.raises(
        SandboxApprovalError, match="does not match the policy decision"
    ):
        service.create_approval(different_target, decision)
