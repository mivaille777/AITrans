from __future__ import annotations

import pytest

from backend.sandbox.docker_runtime import SANDBOX_LABEL, DockerSandboxRuntime
from backend.sandbox.manager import SandboxManager

pytestmark = pytest.mark.docker_integration


@pytest.fixture(scope="module")
def runtime() -> DockerSandboxRuntime:
    candidate = DockerSandboxRuntime(timeout_seconds=30)
    health = candidate.health()
    if not health.available:
        pytest.skip(f"Docker sandbox unavailable: {health.error_code}")
    return candidate


def test_executes_python_and_removes_container(runtime: DockerSandboxRuntime) -> None:
    result = SandboxManager(runtime).execute_python('print("hello sandbox")')

    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout
    assert result.timed_out is False
    _assert_no_sandbox_containers(runtime)


def test_computes_result(runtime: DockerSandboxRuntime) -> None:
    result = SandboxManager(runtime).execute_python(
        "print(sum(i * i for i in range(10)))"
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "285"
    _assert_no_sandbox_containers(runtime)


def test_container_has_no_network(runtime: DockerSandboxRuntime) -> None:
    code = (
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('https://example.com', timeout=2)\n"
        "except Exception:\n"
        "    print('NETWORK_BLOCKED')\n"
        "else:\n"
        "    print('NETWORK_ALLOWED')\n"
    )
    result = SandboxManager(runtime).execute_python(code)

    assert result.exit_code == 0
    assert "NETWORK_BLOCKED" in result.stdout
    assert "NETWORK_ALLOWED" not in result.stdout
    _assert_no_sandbox_containers(runtime)


def test_runtime_errors_are_observable_and_container_is_removed(
    runtime: DockerSandboxRuntime,
) -> None:
    result = SandboxManager(runtime).execute_python(
        'raise RuntimeError("sandbox boom")'
    )

    assert result.exit_code not in (None, 0)
    assert "sandbox boom" in result.stderr
    _assert_no_sandbox_containers(runtime)


def test_timeout_kills_and_removes_container(runtime: DockerSandboxRuntime) -> None:
    short_runtime = DockerSandboxRuntime(
        timeout_seconds=1,
        poll_interval_seconds=0.05,
    )
    result = SandboxManager(short_runtime).execute_python("while True:\n    pass")

    assert result.timed_out is True
    assert result.status == "timed_out"
    _assert_no_sandbox_containers(short_runtime)


def _assert_no_sandbox_containers(runtime: DockerSandboxRuntime) -> None:
    containers = runtime._get_client().containers.list(
        all=True,
        filters={"label": f"{SANDBOX_LABEL}=true"},
    )
    assert containers == []
