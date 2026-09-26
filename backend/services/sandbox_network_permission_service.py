"""Approval and single-use grant handling for exact-host sandbox egress."""

from __future__ import annotations

from backend.models.sandbox_approval import PermissionGrant, SandboxApprovalRequest
from backend.models.sandbox_permissions import ExecutionPolicy, PermissionRequest
from backend.sandbox.network_policy import NetworkPolicy, normalize_hostname
from backend.sandbox.permissions import PermissionPolicyEngine
from backend.services.sandbox_approval_service import (
    SandboxApprovalError,
    SandboxApprovalService,
)


class SandboxNetworkPermissionError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SandboxNetworkPermissionService:
    """Create approvals and convert one exact, run-bound grant into egress policy."""

    def __init__(
        self,
        approval_service: SandboxApprovalService,
        *,
        permission_policy_engine: PermissionPolicyEngine | None = None,
    ) -> None:
        self._approval_service = approval_service
        self._policy_engine = permission_policy_engine or PermissionPolicyEngine()

    def request_approval(
        self,
        host: str,
        *,
        run_id: str,
        tool_call_id: str,
    ) -> SandboxApprovalRequest:
        normalized_host = self._require_host(host)
        if not run_id.strip() or not tool_call_id.strip():
            raise SandboxNetworkPermissionError(
                "network_approval_binding_required",
                "Network approval must be bound to an Agent run and tool call.",
                status_code=400,
            )

        request = PermissionRequest(
            action="network.connect",
            target=normalized_host,
            reason=f"Allow this sandbox run to connect to {normalized_host}.",
            tool_name="command_execute",
            run_id=run_id,
            tool_call_id=tool_call_id,
        )
        decision = self._policy_engine.evaluate(
            request,
            ExecutionPolicy(profile="restricted_network"),
        )
        if decision.decision != "approval_required":
            raise SandboxNetworkPermissionError(
                decision.reason_code,
                decision.reason,
                status_code=403,
            )

        try:
            return self._approval_service.create_approval(request, decision)
        except SandboxApprovalError as exc:
            raise self._approval_error(exc) from exc

    def consume_grant(
        self,
        approval_id: str,
        host: str,
        *,
        run_id: str,
    ) -> NetworkPolicy:
        normalized_host = self._require_host(host)
        if not approval_id.strip() or not run_id.strip():
            raise SandboxNetworkPermissionError(
                "network_approval_binding_required",
                "Network approval must include its ID and the approving run.",
                status_code=400,
            )

        try:
            approval = self._approval_service.get(approval_id)
        except SandboxApprovalError as exc:
            raise self._approval_error(exc) from exc

        expected_scope = {
            "action": "network.connect",
            "workspace_id": "",
            "target": normalized_host,
        }
        if (
            approval.permission_action != "network.connect"
            or approval.target != normalized_host
            or approval.run_id != run_id
            or approval.requested_scope != expected_scope
        ):
            raise SandboxNetworkPermissionError(
                "network_approval_scope_mismatch",
                "The approval is not bound to this host and Agent run.",
                status_code=403,
            )

        try:
            grant = self._approval_service.consume_grant(
                approval_id,
                action="network.connect",
                scope=expected_scope,
                run_id=run_id,
                # The approved tool call may resume with a new call ID. The grant
                # remains bound to its stored request and this exact run and host.
                tool_call_id=approval.tool_call_id,
            )
        except SandboxApprovalError as exc:
            raise self._approval_error(exc) from exc

        if not self._grant_matches(grant, approval, expected_scope):
            raise SandboxNetworkPermissionError(
                "network_approval_scope_mismatch",
                "The approval grant does not match this host and Agent run.",
                status_code=403,
            )
        return NetworkPolicy(mode="restricted", allowed_hosts=(normalized_host,))

    @staticmethod
    def _require_host(host: str) -> str:
        normalized_host = normalize_hostname(host)
        if normalized_host is None:
            raise SandboxNetworkPermissionError(
                "network_host_invalid",
                "Network access requires one valid DNS hostname, not an IP or local address.",
                status_code=400,
            )
        return normalized_host

    @staticmethod
    def _grant_matches(
        grant: PermissionGrant,
        approval: SandboxApprovalRequest,
        expected_scope: dict[str, str | None],
    ) -> bool:
        return (
            grant.approval_id == approval.approval_id
            and grant.action == "network.connect"
            and grant.scope == expected_scope
            and grant.run_id == approval.run_id
            and grant.tool_call_id == approval.tool_call_id
            and grant.single_use is True
        )

    @staticmethod
    def _approval_error(error: SandboxApprovalError) -> SandboxNetworkPermissionError:
        return SandboxNetworkPermissionError(
            error.code,
            str(error),
            status_code=error.status_code,
        )


__all__ = ["SandboxNetworkPermissionError", "SandboxNetworkPermissionService"]
