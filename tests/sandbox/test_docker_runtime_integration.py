from __future__ import annotations

import hashlib

import pytest

from backend.sandbox.docker_runtime import SANDBOX_LABEL, DockerSandboxRuntime
from backend.sandbox.manager import SandboxManager
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
    result = _manager(runtime, tmp_path).execute_python('print("hello sandbox")')

    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout
    assert result.timed_out is False
    _assert_no_sandbox_containers(runtime)


def test_computes_result(runtime: DockerSandboxRuntime, tmp_path) -> None:
    result = _manager(runtime, tmp_path).execute_python(
        "print(sum(i * i for i in range(10)))"
    )

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
    result = _manager(runtime, tmp_path).execute_python(code)

    assert result.exit_code == 0
    assert "NETWORK_BLOCKED" in result.stdout
    assert "NETWORK_ALLOWED" not in result.stdout
    _assert_no_sandbox_containers(runtime)


def test_runtime_errors_are_observable_and_container_is_removed(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _manager(runtime, tmp_path).execute_python(
        'raise RuntimeError("sandbox boom")'
    )

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
    result = _manager(short_runtime, tmp_path).execute_python("while True:\n    pass")

    assert result.timed_out is True
    assert result.status == "timed_out"
    _assert_no_sandbox_containers(short_runtime)


def test_staged_input_is_readable_and_original_path_is_not_returned(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    source = tmp_path / "sample.csv"
    source.write_text("id,value\n1,hello\n", encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    result = _manager(runtime, tmp_path).execute_python(
        "from pathlib import Path\n"
        "print(Path('/input/sample.csv').read_text())",
        input_files=(
            SandboxInputFile("file-1", "sample.csv", source),
        ),
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

    result = _manager(runtime, tmp_path).execute_python(
        "from pathlib import Path\n"
        "Path('/input/sample.csv').write_text('changed')",
        input_files=(
            SandboxInputFile("file-1", "sample.csv", source),
        ),
    )

    assert result.exit_code not in (None, 0)
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    _assert_no_sandbox_containers(runtime)


def test_output_file_is_promoted_with_metadata(
    runtime: DockerSandboxRuntime,
    tmp_path,
) -> None:
    result = _manager(runtime, tmp_path).execute_python(
        "from pathlib import Path\n"
        "Path('/output/result.txt').write_text('ok')"
    )

    assert result.exit_code == 0
    assert len(result.output_files) == 1
    artifact = result.output_files[0]
    promoted = (
        tmp_path
        / "artifacts"
        / result.sandbox_id
        / artifact.relative_path
    )
    assert artifact.relative_path == "result.txt"
    assert artifact.size_bytes == 2
    assert artifact.sha256 == hashlib.sha256(b"ok").hexdigest()
    assert promoted.read_text(encoding="utf-8") == "ok"
    assert str(tmp_path) not in result.model_dump_json()
    _assert_no_sandbox_containers(runtime)


def _assert_no_sandbox_containers(runtime: DockerSandboxRuntime) -> None:
    containers = runtime._get_client().containers.list(
        all=True,
        filters={"label": f"{SANDBOX_LABEL}=true"},
    )
    assert containers == []


def _manager(runtime: DockerSandboxRuntime, tmp_path) -> SandboxManager:
    return SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=tmp_path / "sandboxes",
            artifact_root=tmp_path / "artifacts",
        ),
    )
