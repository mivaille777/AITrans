from __future__ import annotations

from dataclasses import replace

import pytest

from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY, SandboxPolicy


def test_default_policy_has_fixed_isolation_and_resource_bounds() -> None:
    policy = DEFAULT_SANDBOX_POLICY

    assert policy.network_mode == "none"
    assert policy.user == "10001:10001"
    assert policy.read_only_rootfs is True
    assert policy.cap_drop == ("ALL",)
    assert policy.no_new_privileges is True
    assert policy.nano_cpus == 1_000_000_000
    assert policy.memory_limit_bytes == 512 * 1024 * 1024
    assert policy.memory_swap_limit_bytes == policy.memory_limit_bytes
    assert policy.pids_limit == 64
    assert policy.nofile_limit == 256
    assert policy.tmpfs_options == "rw,nosuid,nodev,size=64m,mode=1777"
    assert policy.timeout_seconds == 30
    assert policy.stdout_limit_bytes == 1024 * 1024
    assert policy.stderr_limit_bytes == 1024 * 1024
    assert policy.max_output_files == 64
    assert policy.max_output_file_bytes == 20 * 1024 * 1024
    assert policy.max_total_output_bytes == 50 * 1024 * 1024


@pytest.mark.parametrize(
    "override",
    [
        {"network_mode": "bridge"},
        {"user": "0:0"},
        {"read_only_rootfs": False},
        {"cap_drop": ()},
        {"no_new_privileges": False},
        {"nano_cpus": 1_000_000_001},
        {"memory_limit_bytes": 512 * 1024 * 1024 + 1},
        {"memory_swap_limit_bytes": 513 * 1024 * 1024},
        {"pids_limit": 65},
        {"nofile_limit": 257},
        {"tmpfs_size_bytes": 64 * 1024 * 1024 + 1},
        {"timeout_seconds": 30.1},
        {"stdout_limit_bytes": 1024 * 1024 + 1},
        {"stderr_limit_bytes": 1024 * 1024 + 1},
        {"max_output_files": 65},
        {"max_output_file_bytes": 20 * 1024 * 1024 + 1},
        {"max_total_output_bytes": 50 * 1024 * 1024 + 1},
    ],
)
def test_policy_rejects_relaxed_limits(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(DEFAULT_SANDBOX_POLICY, **override)


def test_policy_can_tighten_limits_for_unit_tests() -> None:
    policy = SandboxPolicy(timeout_seconds=1, stdout_limit_bytes=64)

    assert policy.timeout_seconds == 1
    assert policy.stdout_limit_bytes == 64
