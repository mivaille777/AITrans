"""Default-deny policy engine for sandbox operations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from ipaddress import ip_address

from pydantic import ValidationError

from backend.models.sandbox_permissions import (
    ExecutionPolicy,
    PermissionDecision,
    PermissionRequest,
)
from backend.sandbox.execution_policy import get_sandbox_permission_profile

_KNOWN_ACTIONS = frozenset(
    {
        "filesystem.read",
        "filesystem.write_sandbox",
        "filesystem.apply_host",
        "network.connect",
        "command.execute",
        "secret.read",
    }
)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class PermissionPolicyEngine:
    """Evaluate backend-created requests against a server-owned execution policy."""

    def evaluate(
        self,
        request: PermissionRequest | Mapping[str, object],
        execution_policy: ExecutionPolicy | Mapping[str, object] | None,
    ) -> PermissionDecision:
        if not isinstance(request, PermissionRequest):
            request = PermissionRequest.model_validate(request)
        if execution_policy is None:
            return self._deny(
                "policy.execution_policy_missing",
                "No execution policy is available for this operation.",
            )
        if not isinstance(execution_policy, ExecutionPolicy):
            try:
                execution_policy = ExecutionPolicy.model_validate(execution_policy)
            except ValidationError:
                return self._deny(
                    "policy.execution_policy_invalid",
                    "The execution policy is invalid.",
                )

        profile = get_sandbox_permission_profile(execution_policy.profile)
        if profile is None:
            return self._deny(
                "policy.profile_unknown",
                "The requested sandbox permission profile is not supported.",
            )
        if request.action not in _KNOWN_ACTIONS:
            return self._deny(
                "policy.action_unknown",
                "The requested sandbox action is not supported.",
            )

        action = request.action
        needs_workspace = action in {
            "filesystem.read",
            "filesystem.write_sandbox",
            "filesystem.apply_host",
        }
        if needs_workspace and not execution_policy.workspace_id.strip():
            return self._deny(
                "policy.workspace_required",
                "Filesystem access requires a selected workspace.",
            )

        scope = self._scope(request, execution_policy)
        if action == "filesystem.read":
            if profile.filesystem_read:
                return self._allow("The selected workspace may be read.", scope)
            return self._deny("policy.filesystem_read_denied", "Workspace reading is disabled.")

        if action == "filesystem.write_sandbox":
            if profile.filesystem_write_sandbox:
                return self._allow("The sandbox workspace may be edited.", scope)
            return self._deny(
                "policy.filesystem_write_denied",
                "Editing the sandbox workspace is disabled.",
            )

        if action == "filesystem.apply_host":
            if not request.target.strip():
                return self._deny(
                    "policy.target_required",
                    "Applying changes requires an explicit target path.",
                )
            if profile.filesystem_apply_host == "approval_required":
                return PermissionDecision(
                    decision="approval_required",
                    reason_code="policy.approval_required",
                    reason="Applying workspace changes requires user approval.",
                    granted_scope=scope,
                )
            return self._deny(
                "policy.filesystem_apply_denied",
                "Applying changes to the host workspace is disabled.",
            )

        if action == "network.connect":
            host = self._normalize_host(request.target)
            allowed_hosts = {
                normalized
                for value in execution_policy.network_allowlist
                if (normalized := self._normalize_host(value)) is not None
            }
            if profile.network == "allowlist" and host and host in allowed_hosts:
                return self._allow(
                    "The requested host is in the execution allowlist.",
                    {"action": action, "host": host},
                )
            return self._deny(
                "policy.network_denied",
                "Network access is disabled or the host is not allowlisted.",
            )

        if action == "command.execute":
            if profile.command_execution:
                return self._allow(
                    "Commands may run inside the isolated sandbox.",
                    {"action": action, "runtime": "sandbox"},
                )
            return self._deny(
                "policy.command_denied",
                "Command execution is disabled for this profile.",
            )

        # Secrets remain denied for every P0 profile.
        return self._deny("policy.secret_denied", "Secret access is disabled.")

    @classmethod
    def _scope(
        cls,
        request: PermissionRequest,
        execution_policy: ExecutionPolicy,
    ) -> dict[str, str | bool | int | None]:
        return {
            "action": request.action,
            "workspace_id": execution_policy.workspace_id,
            "target": request.target or None,
        }

    @staticmethod
    def _normalize_host(value: str) -> str | None:
        host = value.strip().lower().rstrip(".")
        if not host or ":" in host or "/" in host or "\\" in host:
            return None
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            return None
        labels = host.split(".")
        if len(host) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
            return None
        return host

    @staticmethod
    def _allow(
        reason: str,
        granted_scope: dict[str, str | bool | int | None],
    ) -> PermissionDecision:
        return PermissionDecision(
            decision="allow",
            reason_code="policy.allowed",
            reason=reason,
            granted_scope=granted_scope,
        )

    @staticmethod
    def _deny(reason_code: str, reason: str) -> PermissionDecision:
        return PermissionDecision(
            decision="deny",
            reason_code=reason_code,
            reason=reason,
        )


__all__ = ["PermissionPolicyEngine"]
