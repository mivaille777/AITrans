from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from backend.models.sandbox_permissions import ExecutionPolicy
from backend.sandbox.command_models import SandboxCommandRequest
from backend.sandbox.command_runtime import SandboxCommandExecutor
from backend.sandbox.docker_runtime import SANDBOX_LABEL, DockerSandboxRuntime
from backend.sandbox.manager import SandboxManager
from backend.sandbox.workspace import SandboxWorkspaceManager

pytestmark = pytest.mark.docker_integration


@pytest.fixture(scope="module")
def runtime() -> DockerSandboxRuntime:
    candidate = DockerSandboxRuntime(timeout_seconds=30)
    health = candidate.health()
    if not health.available:
        pytest.skip(f"Docker sandbox unavailable: {health.error_code}")
    return candidate


def _execute(
    runtime: DockerSandboxRuntime, tmp_path: Path, request: SandboxCommandRequest
):
    temp_root = Path(tempfile.gettempdir()) / "aitrans-command-tests" / uuid4().hex
    manager = SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=temp_root / "sandboxes",
            artifact_root=tmp_path / "artifacts",
        ),
    )
    try:
        return SandboxCommandExecutor(manager).execute(
            request,
            execution_policy=ExecutionPolicy(profile="workspace_write"),
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_executes_python_version_in_docker(
    runtime: DockerSandboxRuntime, tmp_path: Path
):
    result = _execute(
        runtime, tmp_path, SandboxCommandRequest(argv=["python", "--version"])
    )

    assert result.status == "succeeded"
    assert "Python 3.12" in result.stdout
    _assert_no_sandbox_containers(runtime)


def test_pytest_is_installed_in_command_image(
    runtime: DockerSandboxRuntime, tmp_path: Path
):
    result = _execute(
        runtime,
        tmp_path,
        SandboxCommandRequest(argv=["python", "-m", "pytest", "--version"]),
    )

    assert result.status == "succeeded"
    assert "pytest 9.0.3" in result.stdout
    _assert_no_sandbox_containers(runtime)


def test_command_timeout_stops_only_the_sandboxed_process(
    runtime: DockerSandboxRuntime,
    tmp_path: Path,
):
    result = _execute(
        runtime,
        tmp_path,
        SandboxCommandRequest(
            argv=["python", "-c", "import time; time.sleep(10)"],
            timeout_seconds=0.5,
        ),
    )

    assert result.status == "timed_out"
    assert result.timed_out is True
    _assert_no_sandbox_containers(runtime)


def test_command_output_flood_is_bounded(runtime: DockerSandboxRuntime, tmp_path: Path):
    result = _execute(
        runtime,
        tmp_path,
        SandboxCommandRequest(
            argv=["python", "-c", "import sys; sys.stdout.write('x' * 2000000)"]
        ),
    )

    assert result.status == "output_limit_exceeded"
    assert result.output_limit_exceeded is True
    assert result.stdout_bytes <= runtime.policy.stdout_limit_bytes
    _assert_no_sandbox_containers(runtime)


def _assert_no_sandbox_containers(runtime: DockerSandboxRuntime) -> None:
    containers = runtime._get_client().containers.list(
        all=True,
        filters={"label": f"{SANDBOX_LABEL}=true"},
    )
    assert containers == []
