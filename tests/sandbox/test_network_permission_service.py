from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.sandbox.network_policy import NetworkPolicy
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.sandbox_network_permission_service import (
    SandboxNetworkPermissionError,
    SandboxNetworkPermissionService,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _service(*, clock=None, ttl_seconds: int = 300):
    approvals = SandboxApprovalService(ttl_seconds=ttl_seconds, clock=clock)
    return SandboxNetworkPermissionService(approvals), approvals


def _request(service: SandboxNetworkPermissionService):
    return service.request_approval(
        "PyPI.org.",
        run_id="run-1",
        tool_call_id="call-1",
    )


def test_network_request_creates_exact_host_run_bound_approval() -> None:
    service, approvals = _service()

    request = _request(service)

    assert request.status == "pending"
    assert request.permission_action == "network.connect"
    assert request.target == "pypi.org"
    assert request.run_id == "run-1"
    assert request.tool_call_id == "call-1"
    assert request.requested_scope == {
        "action": "network.connect",
        "workspace_id": "",
        "target": "pypi.org",
    }
    assert approvals.list_pending() == [request]


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.1", "169.254.169.254", "db.internal", "https://pypi.org"],
)
def test_invalid_or_local_host_cannot_create_approval(host: str) -> None:
    service, approvals = _service()

    with pytest.raises(SandboxNetworkPermissionError) as error:
        service.request_approval(host, run_id="run-1", tool_call_id="call-1")

    assert error.value.code == "network_host_invalid"
    assert approvals.list_pending() == []


def test_network_grant_allows_only_approved_exact_host_once() -> None:
    service, approvals = _service()
    approval = _request(service)
    approvals.approve(approval.approval_id)

    policy = service.consume_grant(
        approval.approval_id,
        "PYPI.org",
        run_id="run-1",
    )

    assert policy == NetworkPolicy(mode="restricted", allowed_hosts=("pypi.org",))
    assert approvals.get(approval.approval_id).status == "consumed"
    with pytest.raises(SandboxNetworkPermissionError) as error:
        service.consume_grant(approval.approval_id, "pypi.org", run_id="run-1")
    assert error.value.code == "approval_grant_replayed"


def test_network_grant_is_bound_to_its_run_and_host() -> None:
    service, approvals = _service()
    approval = _request(service)
    approvals.approve(approval.approval_id)

    with pytest.raises(SandboxNetworkPermissionError) as wrong_run:
        service.consume_grant(approval.approval_id, "pypi.org", run_id="run-2")
    assert wrong_run.value.code == "network_approval_scope_mismatch"

    with pytest.raises(SandboxNetworkPermissionError) as wrong_host:
        service.consume_grant(approval.approval_id, "github.com", run_id="run-1")
    assert wrong_host.value.code == "network_approval_scope_mismatch"

    # Failed scope checks leave the single-use grant available for its exact scope.
    policy = service.consume_grant(
        approval.approval_id,
        "pypi.org",
        run_id="run-1",
    )
    assert policy.allowed_hosts == ("pypi.org",)


def test_expired_approved_network_grant_cannot_be_consumed() -> None:
    clock = MutableClock()
    service, approvals = _service(clock=clock, ttl_seconds=5)
    approval = _request(service)
    approvals.approve(approval.approval_id)
    clock.value += timedelta(seconds=6)

    with pytest.raises(SandboxNetworkPermissionError) as error:
        service.consume_grant(approval.approval_id, "pypi.org", run_id="run-1")

    assert error.value.code == "approval_expired"
    assert approvals.get(approval.approval_id).status == "expired"


def test_network_approval_requires_run_and_tool_call_binding() -> None:
    service, approvals = _service()

    with pytest.raises(SandboxNetworkPermissionError) as error:
        service.request_approval("pypi.org", run_id="", tool_call_id="call-1")

    assert error.value.code == "network_approval_binding_required"
    assert approvals.list_pending() == []
