from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models.sandbox_permissions import ExecutionPolicy, PermissionRequest
from backend.sandbox.permissions import PermissionPolicyEngine


@pytest.fixture
def engine() -> PermissionPolicyEngine:
    return PermissionPolicyEngine()


def _request(action: str, *, target: str = "src/app.py") -> PermissionRequest:
    return PermissionRequest(
        action=action,
        target=target,
        reason="P0 permission policy test",
        tool_name="test_tool",
        run_id="run-test",
        tool_call_id="call-test",
    )


def _policy(
    profile: str, *, workspace_id: str = "workspace-test", **kwargs
) -> ExecutionPolicy:
    return ExecutionPolicy(profile=profile, workspace_id=workspace_id, **kwargs)


def test_read_only_profile_allows_selected_workspace_read(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(_request("filesystem.read"), _policy("read_only"))

    assert decision.decision == "allow"
    assert decision.reason_code == "policy.allowed"
    assert decision.granted_scope["workspace_id"] == "workspace-test"


def test_read_only_profile_denies_sandbox_workspace_write(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(
        _request("filesystem.write_sandbox"), _policy("read_only")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.filesystem_write_denied"


def test_workspace_write_profile_allows_sandbox_workspace_edit(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(
        _request("filesystem.write_sandbox"), _policy("workspace_write")
    )

    assert decision.decision == "allow"


def test_host_apply_requires_approval(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(
        _request("filesystem.apply_host"), _policy("workspace_write")
    )

    assert decision.decision == "approval_required"
    assert decision.granted_scope["target"] == "src/app.py"


def test_workspace_write_profile_does_not_allow_network(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(
        _request("network.connect", target="example.com"),
        _policy("workspace_write", network_allowlist=("example.com",)),
    )

    assert decision.decision == "deny"


def test_restricted_network_requires_exact_allowlisted_hostname(
    engine: PermissionPolicyEngine,
) -> None:
    allowed = engine.evaluate(
        _request("network.connect", target="EXAMPLE.com."),
        _policy("restricted_network", network_allowlist=("example.com",)),
    )
    denied = engine.evaluate(
        _request("network.connect", target="other.example.com"),
        _policy("restricted_network", network_allowlist=("example.com",)),
    )

    assert allowed.decision == "allow"
    assert allowed.granted_scope["host"] == "example.com"
    assert denied.decision == "deny"


def test_unknown_action_is_denied(engine: PermissionPolicyEngine) -> None:
    decision = engine.evaluate(_request("docker.socket_mount"), _policy("read_only"))

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.action_unknown"


def test_command_execution_is_limited_to_the_server_allowlist(
    engine: PermissionPolicyEngine,
) -> None:
    allowed = engine.evaluate(
        _request("command.execute", target="python"), _policy("read_only")
    )
    denied = engine.evaluate(
        _request("command.execute", target="/bin/sh"), _policy("read_only")
    )

    assert allowed.decision == "allow"
    assert allowed.granted_scope["executable"] == "python"
    assert denied.decision == "deny"
    assert denied.reason_code == "policy.command_executable_denied"


def test_unknown_profile_is_denied(engine: PermissionPolicyEngine) -> None:
    decision = engine.evaluate(
        _request("command.execute"), _policy("danger_full_access")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.profile_unknown"


def test_filesystem_access_is_denied_without_workspace(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(
        _request("filesystem.read"), _policy("read_only", workspace_id="")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.workspace_required"


def test_host_apply_is_denied_for_read_only_profile(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(_request("filesystem.apply_host"), _policy("read_only"))

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.filesystem_apply_denied"


def test_secrets_are_denied_for_all_profiles(
    engine: PermissionPolicyEngine,
) -> None:
    for profile in ("read_only", "workspace_write", "restricted_network"):
        decision = engine.evaluate(_request("secret.read"), _policy(profile))
        assert decision.decision == "deny"


def test_agent_cannot_supply_full_access_permission_field() -> None:
    with pytest.raises(ValidationError):
        PermissionRequest.model_validate(
            {
                "action": "command.execute",
                "reason": "untrusted tool request",
                "permission": "full_access",
            }
        )


def test_missing_execution_policy_denies_by_default(
    engine: PermissionPolicyEngine,
) -> None:
    decision = engine.evaluate(_request("command.execute"), None)

    assert decision.decision == "deny"
    assert decision.reason_code == "policy.execution_policy_missing"
