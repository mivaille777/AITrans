from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.sandbox.docker_runtime import DockerSandboxRuntime
from backend.sandbox.errors import (
    DockerNotLinuxError,
    DockerUnavailableError,
    SandboxImageMissingError,
)
from backend.sandbox.models import SandboxExecutionRequest


class FakeContainer:
    def __init__(self, *, timeout_after_polls: int | None = 1) -> None:
        self.status = "created"
        self.attrs = {"State": {"Status": "created", "ExitCode": None, "OOMKilled": False}}
        self.timeout_after_polls = timeout_after_polls
        self.polls = 0
        self.removed = False
        self.killed = False

    def start(self) -> None:
        self.status = "running"
        self.attrs["State"]["Status"] = self.status

    def reload(self) -> None:
        self.polls += 1
        if self.killed:
            self.attrs["State"].update(
                Status="exited",
                ExitCode=137,
                OOMKilled=False,
            )
            self.status = "exited"
        elif self.timeout_after_polls is not None and self.polls >= self.timeout_after_polls:
            self.attrs["State"].update(Status="exited", ExitCode=0, OOMKilled=False)
            self.status = "exited"
        else:
            self.attrs["State"]["Status"] = "running"
            self.status = "running"

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> dict[str, int]:
        return {"StatusCode": 137}

    def logs(self, *, stdout: bool, stderr: bool) -> bytes:
        if stdout:
            return b"ok\n"
        if stderr:
            return b""
        return b""

    def remove(self, *, force: bool = False) -> None:
        assert force is True
        self.removed = True


class FakeDockerClient:
    def __init__(self, container: FakeContainer | None = None) -> None:
        self.container = container or FakeContainer()
        self.containers = SimpleNamespace(create=self.create)
        self.images = SimpleNamespace(get=self.get_image)

    def ping(self) -> bool:
        return True

    def info(self) -> dict[str, str]:
        return {"OSType": "linux"}

    def get_image(self, image: str) -> object:
        return object()

    def create(self, **kwargs) -> FakeContainer:
        self.create_kwargs = kwargs
        return self.container


def test_runtime_uses_no_network_and_removes_completed_container() -> None:
    container = FakeContainer(timeout_after_polls=1)
    client = FakeDockerClient(container)
    runtime = DockerSandboxRuntime(client=client)

    result = runtime.execute_python(
        SandboxExecutionRequest(sandbox_id="sb_unit", code="print('ok')")
    )

    assert result.stdout == "ok\n"
    assert result.exit_code == 0
    assert result.status == "succeeded"
    assert client.create_kwargs["network_mode"] == "none"
    assert client.create_kwargs["labels"]["com.aitrans.sandbox_id"] == "sb_unit"
    assert container.removed is True


def test_runtime_kills_timed_out_container_and_removes_it() -> None:
    container = FakeContainer(timeout_after_polls=None)
    client = FakeDockerClient(container)
    runtime = DockerSandboxRuntime(
        client=client,
        timeout_seconds=0.01,
        poll_interval_seconds=0.005,
    )

    result = runtime.execute_python(
        SandboxExecutionRequest(sandbox_id="sb_timeout", code="while True: pass")
    )

    assert result.timed_out is True
    assert result.status == "timed_out"
    assert container.killed is True
    assert container.removed is True


def test_health_reports_missing_image_with_stable_code() -> None:
    class MissingImageClient(FakeDockerClient):
        def get_image(self, image: str) -> object:
            from docker.errors import ImageNotFound

            raise ImageNotFound("missing")

    health = DockerSandboxRuntime(client=MissingImageClient()).health()

    assert health.available is False
    assert health.error_code == SandboxImageMissingError.code


def test_health_reports_docker_unavailable_with_stable_code(monkeypatch) -> None:
    from docker.errors import DockerException

    def unavailable(*args, **kwargs):
        raise DockerException("private daemon detail")

    monkeypatch.setattr("backend.sandbox.docker_runtime.docker.from_env", unavailable)
    health = DockerSandboxRuntime().health()

    assert health.available is False
    assert health.error_code == DockerUnavailableError.code
    assert "private daemon detail" not in health.message


def test_health_requires_linux_containers() -> None:
    client = FakeDockerClient()
    client.info = lambda: {"OSType": "windows"}

    health = DockerSandboxRuntime(client=client).health()

    assert health.available is False
    assert health.error_code == DockerNotLinuxError.code


@pytest.mark.parametrize("image", ["", "python:latest", "aitrans-python-sandbox:latest"])
def test_runtime_rejects_unpinned_or_missing_image(image: str) -> None:
    with pytest.raises(ValueError):
        DockerSandboxRuntime(image=image)
