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


def test_executes_python_and_removes_container(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _execute(runtime, tmp_path, 'print("hello sandbox")')

    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout
    assert result.timed_out is False
    _assert_no_sandbox_containers(runtime)


def test_computes_result(runtime: DockerSandboxRuntime, tmp_path) -> None:
    result = _execute(runtime, tmp_path, "print(sum(i * i for i in range(10)))")

    assert result.exit_code == 0
    assert result.stdout.strip() == "285"
    _assert_no_sandbox_containers(runtime)


def test_container_has_no_network(runtime: DockerSandboxRuntime, tmp_path) -> None:
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


def test_runtime_errors_are_observable_and_container_is_removed(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _execute(runtime, tmp_path, 'raise RuntimeError("sandbox boom")')

    assert result.exit_code not in (None, 0)
    assert "sandbox boom" in result.stderr
    _assert_no_sandbox_containers(runtime)


def test_timeout_kills_and_removes_container(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    short_runtime = DockerSandboxRuntime(
        timeout_seconds=1,
        poll_interval_seconds=0.05,
    )
    result = _execute(short_runtime, tmp_path, "while True:\n    pass")

    assert result.timed_out is True
    assert result.status == "timed_out"
    _assert_no_sandbox_containers(short_runtime)


def test_long_idle_execution_reaches_runtime_timeout(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    long_runtime = DockerSandboxRuntime(timeout_seconds=6)

    result = _execute(long_runtime, tmp_path, "while True: pass")

    assert result.timed_out is True
    assert result.status == "timed_out"
    _assert_no_sandbox_containers(long_runtime)


def test_staged_input_is_readable_and_original_path_is_not_returned(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    source = tmp_path / "sample.csv"
    source.write_text("id,value\n1,hello\n", encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\nprint(Path('/input/sample.csv').read_text())",
        input_files=(SandboxInputFile("file-1", "sample.csv", source),),
    )

    assert result.exit_code == 0
    assert "1,hello" in result.stdout
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    assert str(source) not in result.model_dump_json()
    _assert_no_sandbox_containers(runtime)


def test_staged_input_is_read_only(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    source = tmp_path / "sample.csv"
    original = "id,value\n1,original\n"
    source.write_text(original, encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\nPath('/input/sample.csv').write_text('changed')",
        input_files=(SandboxInputFile("file-1", "sample.csv", source),),
    )

    assert result.exit_code not in (None, 0)
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    _assert_no_sandbox_containers(runtime)


def test_output_file_is_promoted_with_metadata(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\nPath('/output/result.txt').write_text('ok')",
    )

    assert result.exit_code == 0
    assert len(result.output_files) == 1
    artifact = result.output_files[0]
    promoted = tmp_path / "artifacts" / result.sandbox_id / artifact.relative_path
    assert artifact.relative_path == "result.txt"
    assert artifact.size_bytes == 2
    assert artifact.sha256 == hashlib.sha256(b"ok").hexdigest()
    assert promoted.read_text(encoding="utf-8") == "ok"
    assert str(tmp_path) not in result.model_dump_json()
    _assert_no_sandbox_containers(runtime)


def test_container_runs_non_root_and_has_no_docker_socket(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _execute(
        runtime,
        tmp_path,
        "import os\n"
        "from pathlib import Path\n"
        "print(os.getuid())\n"
        "print(Path('/var/run/docker.sock').exists())",
    )

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["10001", "False"]
    _assert_no_sandbox_containers(runtime)


def test_container_uses_the_default_seccomp_profile(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\n"
        "status = Path('/proc/self/status').read_text().splitlines()\n"
        "print(next(line.split()[1] for line in status if line.startswith('Seccomp:')))",
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "2"
    _assert_no_sandbox_containers(runtime)


def test_container_cannot_exceed_the_pid_limit(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
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


def test_container_root_filesystem_is_read_only(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _execute(
        runtime,
        tmp_path,
        "from pathlib import Path\nPath('/etc/aitrans-test').write_text('no')",
    )

    assert result.exit_code not in (None, 0)
    assert "Read-only file system" in result.stderr
    _assert_no_sandbox_containers(runtime)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_flood_is_stopped_at_the_policy_limit(
    runtime: DockerSandboxRuntime,
    tmp_path,
    stream: str,
) -> None:
    write_line = (
        "print('A' * 100000)"
        if stream == "stdout"
        else "print('A' * 100000, file=sys.stderr)"
    )
    result = _execute(runtime, tmp_path, f"import sys\nwhile True:\n    {write_line}")

    assert result.status == "output_limit_exceeded"
    assert result.output_limit_exceeded is True
    if stream == "stdout":
        assert result.stdout_bytes <= runtime.policy.stdout_limit_bytes
        assert len(result.stdout.encode("utf-8")) <= runtime.policy.stdout_limit_bytes
    else:
        assert result.stderr_bytes <= runtime.policy.stderr_limit_bytes
        assert len(result.stderr.encode("utf-8")) <= runtime.policy.stderr_limit_bytes
    _assert_no_sandbox_containers(runtime)


def test_memory_limit_is_reported_as_oom(
    tmp_path,
) -> None:
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
    # temp path contains non-ASCII characters. Keep all bind sources in an
    # ASCII-only path while still storing promoted artifacts under tmp_path.
    temp_root = Path(tempfile.gettempdir()) / "aitrans-sandbox-tests" / uuid4().hex
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
