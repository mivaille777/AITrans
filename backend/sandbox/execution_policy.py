"""System-owned sandbox execution profiles."""

from __future__ import annotations

from types import MappingProxyType

from backend.models.sandbox_permissions import (
    SandboxPermissionProfile,
    SandboxPermissionProfileName,
)

_PROFILES = {
    "read_only": SandboxPermissionProfile(
        name="read_only",
        filesystem_read=True,
        filesystem_write_sandbox=False,
        filesystem_apply_host="deny",
        network="none",
        command_execution=True,
        secrets="none",
    ),
    "workspace_write": SandboxPermissionProfile(
        name="workspace_write",
        filesystem_read=True,
        filesystem_write_sandbox=True,
        filesystem_apply_host="approval_required",
        network="none",
        command_execution=True,
        secrets="none",
    ),
    "restricted_network": SandboxPermissionProfile(
        name="restricted_network",
        filesystem_read=True,
        filesystem_write_sandbox=True,
        filesystem_apply_host="approval_required",
        network="allowlist",
        command_execution=True,
        secrets="none",
    ),
}

SANDBOX_PERMISSION_PROFILES = MappingProxyType(_PROFILES)


def get_sandbox_permission_profile(
    name: str,
) -> SandboxPermissionProfile | None:
    """Return a known immutable profile, or ``None`` for unknown names."""

    return SANDBOX_PERMISSION_PROFILES.get(name)


def require_sandbox_permission_profile(
    name: SandboxPermissionProfileName,
) -> SandboxPermissionProfile:
    """Return a profile for typed system configuration."""

    return SANDBOX_PERMISSION_PROFILES[name]


__all__ = [
    "SANDBOX_PERMISSION_PROFILES",
    "get_sandbox_permission_profile",
    "require_sandbox_permission_profile",
]
