from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from backend.sandbox.docker_runtime import SANDBOX_LABEL, DockerSandboxRuntime
from backend.sandbox.manager import SandboxManager
from backend.sandbox.policy import SandboxPolicy
from backend.sandbox.workspace import SandboxInputFile, SandboxWorkspaceManager

pytestmark = pytest.mark.docker_integration


@pytest.fixture(scope="module")
def runtime() -> DockerSandboxRuntime:
    candidate = DockerSandboxRuntime(timeout_seconds=30)
    health = candidate.health()
    if not health.available:
        pytest.skip(f"Docker sandbox unavailable: {health.error_code}")
    return candidate


def test_container_runs_as_uid_10001(runtime: DockerSandboxRuntime, tmp_path: Path) -> None:
    result = _execute(runtime, tmp_path, "import os\nprint(os.getuid())")

    assert result.exit_code == 0
    assert result.stdout.strip() == "10001"
    _assert_no_sandbox_containers(runtime)


def test_docker_socket_is_not_available(runtime: DockerSandboxRuntime, tmp_path: Path) -> None:
    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\n"
        "print(Path('/var/run/docker.sock').exists())",
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "False"
    _assert_no_sandbox_containers(runtime)


def test_root_filesystem_is_read_only(runtime: DockerSandboxRuntime, tmp_path: Path) -> None:
    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\nPath('/etc/p0_escape').write_text('x')",
    )

    assert result.exit_code not in (None, 0)
    assert "Read-only file system" in result.stderr
    _assert_no_sandbox_containers(runtime)


def test_network_is_disabled_by_default(
    runtime: DockerSandboxRuntime,
    tmp_path: Path,
) -> None:
    code = (
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('https://example.com', timeout=2)\n"
        "except Exception:\n"
        "    print('NETWORK_BLOCKED')\n"
        "else:\n"
        "    print('NETWORK_ALLOWED')\n"
    )
    result = _execute(runtime, tmp_path, code)

    assert result.exit_code == 0
    assert "NETWORK_BLOCKED" in result.stdout
    assert "NETWORK_ALLOWED" not in result.stdout
    _assert_no_sandbox_containers(runtime)


def test_host_workspace_path_is_not_mounted_into_container(
    runtime: DockerSandboxRuntime,
    tmp_path: Path,
) -> None:
    host_file = tmp_path / "host-private" / "sample.txt"
    host_file.parent.mkdir()
    host_file.write_text("host source", encoding="utf-8")
    expected_hash = hashlib.sha256(host_file.read_bytes()).hexdigest()
    code = (
        "from pathlib import Path\n"
        f"host_path = Path({str(host_file.resolve())!r})\n"
        "print('HOST_PATH_VISIBLE' if host_path.exists() else 'HOST_PATH_UNAVAILABLE')\n"
        "print(Path('/input/sample.txt').read_text())\n"
    )

    result = _execute(
        runtime,
        tmp_path,
        code,
        input_files=(SandboxInputFile("file-1", "sample.txt", host_file),),
    )

    assert result.exit_code == 0
    assert "HOST_PATH_UNAVAILABLE" in result.stdout
    assert "HOST_PATH_VISIBLE" not in result.stdout
    assert "host source" in result.stdout
    assert hashlib.sha256(host_file.read_bytes()).hexdigest() == expected_hash
    assert str(host_file.resolve()) not in result.model_dump_json()
    _assert_no_sandbox_containers(runtime)


def test_pid_limit_is_enforced(runtime: DockerSandboxRuntime, tmp_path: Path) -> None:
    code = (
        "import os, signal, time\n"
        "children = []\n"
        "try:\n"
        "    while True:\n"
        "        pid = os.fork()\n"
        "        if pid == 0:\n"
        "            time.sleep(30)\n"
        "            os._exit(0)\n"
        "        children.append(pid)\n"
        "except OSError as error:\n"
        "    print('PID_LIMIT', len(children), error.errno)\n"
        "finally:\n"
        "    for pid in children:\n"
        "        try: os.kill(pid, signal.SIGTERM)\n"
        "        except ProcessLookupError: pass\n"
        "    for pid in children:\n"
        "        try: os.waitpid(pid, 0)\n"
        "        except ChildProcessError: pass\n"
    )
    result = _execute(runtime, tmp_path, code)

    assert result.exit_code == 0
    assert "PID_LIMIT" in result.stdout
    child_count = int(result.stdout.split()[1])
    assert child_count < runtime.policy.pids_limit
    _assert_no_sandbox_containers(runtime)


def test_memory_limit_reports_oom_killed(tmp_path: Path) -> None:
    memory_limit = 64 * 1024 * 1024
    memory_runtime = DockerSandboxRuntime(
        policy=SandboxPolicy(
            memory_limit_bytes=memory_limit,
            memory_swap_limit_bytes=memory_limit,
        )
    )
    code = "blocks = []\nwhile True:\n    blocks.append(bytearray(20 * 1024 * 1024))\n"
    result = _execute(memory_runtime, tmp_path, code)

    assert result.oom_killed is True
    assert result.status == "oom_killed"
    _assert_no_sandbox_containers(memory_runtime)


def test_infinite_loop_times_out(runtime: DockerSandboxRuntime, tmp_path: Path) -> None:
    short_runtime = DockerSandboxRuntime(timeout_seconds=1, poll_interval_seconds=0.05)
    result = _execute(short_runtime, tmp_path, "while True:\n    pass")

    assert result.timed_out is True
    assert result.status == "timed_out"
    _assert_no_sandbox_containers(short_runtime)


def _assert_no_sandbox_containers(runtime: DockerSandboxRuntime) -> None:
    containers = runtime._get_client().containers.list(
        all=True,
        filters={"label": f"{SANDBOX_LABEL}=true"},
    )
    assert containers == []


def _execute(
    runtime: DockerSandboxRuntime,
    tmp_path: Path,
    code: str,
    *,
    input_files: tuple[SandboxInputFile, ...] = (),
):
    # Docker Desktop's Windows file sharing can stall when pytest's generated
    # temp path contains non-ASCII characters, so bind sources use an ASCII path.
    temp_root = Path(tempfile.gettempdir()) / "aitrans-sandbox-p0-tests" / uuid4().hex
    try:
        return SandboxManager(
            runtime,
            SandboxWorkspaceManager(
                sandbox_root=temp_root / "sandboxes",
                artifact_root=tmp_path / "artifacts",
            ),
        ).execute_python(code, input_files=input_files)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
