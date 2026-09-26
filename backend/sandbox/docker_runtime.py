"""One-shot Docker runtime for untrusted Python code."""

from __future__ import annotations

import time
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from backend.sandbox.errors import (
    DockerNotLinuxError,
    DockerUnavailableError,
    SandboxCleanupError,
    SandboxCreateError,
    SandboxExecutionError,
    SandboxImageMissingError,
    SandboxStartError,
)
from backend.sandbox.models import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxRuntimeHealth,
)

DEFAULT_IMAGE = "aitrans-python-sandbox:v1"
SANDBOX_LABEL = "com.aitrans.sandbox"
SANDBOX_ID_LABEL = "com.aitrans.sandbox_id"
RUNTIME_LABEL = "com.aitrans.runtime"


class DockerSandboxRuntime:
    """Docker-backed runtime that always removes the container it creates."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.1,
        docker_api_timeout_seconds: int = 5,
        client: Any | None = None,
    ) -> None:
        if not image or image.strip().lower().endswith(":latest"):
            raise ValueError("A pinned sandbox image tag is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive.")
        if docker_api_timeout_seconds <= 0:
            raise ValueError("docker_api_timeout_seconds must be positive.")

        self.image = image
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.docker_api_timeout_seconds = docker_api_timeout_seconds
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = docker.from_env(
                    timeout=self.docker_api_timeout_seconds
                )
            except DockerException as exc:
                raise DockerUnavailableError(
                    "Docker daemon is unavailable."
                ) from exc
        return self._client

    def health(self) -> SandboxRuntimeHealth:
        try:
            client = self._get_client()
            client.ping()
            info = client.info()
        except DockerUnavailableError as exc:
            return SandboxRuntimeHealth(
                available=False,
                image=self.image,
                error_code=exc.code,
                message=str(exc),
            )
        except DockerException:
            return SandboxRuntimeHealth(
                available=False,
                image=self.image,
                error_code=DockerUnavailableError.code,
                message="Docker daemon is unavailable.",
            )

        server_os = str(info.get("OSType", "")).lower()
        if server_os != "linux":
            return SandboxRuntimeHealth(
                available=False,
                image=self.image,
                server_os=server_os,
                error_code=DockerNotLinuxError.code,
                message="Docker must use Linux containers.",
            )

        try:
            client.images.get(self.image)
        except ImageNotFound:
            return SandboxRuntimeHealth(
                available=False,
                image=self.image,
                server_os=server_os,
                error_code=SandboxImageMissingError.code,
                message="The configured sandbox image is not built.",
            )
        except DockerException:
            return SandboxRuntimeHealth(
                available=False,
                image=self.image,
                server_os=server_os,
                error_code=DockerUnavailableError.code,
                message="Docker daemon is unavailable.",
            )

        return SandboxRuntimeHealth(
            available=True,
            image=self.image,
            server_os=server_os,
            message="Docker sandbox runtime is ready.",
        )

    def _ensure_ready(self) -> None:
        health = self.health()
        if health.available:
            return
        message = health.message or "Docker sandbox runtime is unavailable."
        if health.error_code == DockerNotLinuxError.code:
            raise DockerNotLinuxError(message)
        if health.error_code == SandboxImageMissingError.code:
            raise SandboxImageMissingError(message)
        raise DockerUnavailableError(message)

    def execute_python(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        self._ensure_ready()
        client = self._get_client()
        container_name = f"aitrans-sb-{request.sandbox_id}"
        container = None
        started_at = time.monotonic()
        timed_out = False
        exit_code: int | None = None
        oom_killed = False
        stdout = ""
        stderr = ""
        primary_error: BaseException | None = None

        try:
            try:
                container = client.containers.create(
                    image=self.image,
                    command=["python", "-c", request.code],
                    name=container_name,
                    labels={
                        SANDBOX_LABEL: "true",
                        SANDBOX_ID_LABEL: request.sandbox_id,
                        RUNTIME_LABEL: "python",
                    },
                    network_mode="none",
                    working_dir="/workspace",
                    detach=True,
                    stdin_open=False,
                    tty=False,
                )
            except DockerException as exc:
                raise SandboxCreateError(
                    "Failed to create the Python sandbox container."
                ) from exc

            try:
                container.start()
            except DockerException as exc:
                raise SandboxStartError(
                    "Failed to start the Python sandbox container."
                ) from exc

            deadline = time.monotonic() + self.timeout_seconds
            while True:
                try:
                    container.reload()
                except NotFound as exc:
                    raise SandboxExecutionError(
                        "Python sandbox container disappeared during execution."
                    ) from exc
                except DockerException as exc:
                    raise SandboxExecutionError(
                        "Failed to inspect the Python sandbox container."
                    ) from exc

                state = (container.attrs or {}).get("State", {})
                if str(state.get("Status", "")).lower() not in {
                    "created",
                    "restarting",
                    "running",
                    "paused",
                }:
                    exit_code = state.get("ExitCode")
                    oom_killed = bool(state.get("OOMKilled", False))
                    break

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    try:
                        container.kill()
                    except NotFound:
                        pass
                    except DockerException as exc:
                        raise SandboxExecutionError(
                            "Failed to stop the timed out Python sandbox."
                        ) from exc
                    try:
                        container.wait(timeout=self.docker_api_timeout_seconds)
                    except (DockerException, TypeError):
                        # Container removal in finally remains mandatory even
                        # when Docker cannot return the final state promptly.
                        pass
                    break
                time.sleep(min(self.poll_interval_seconds, remaining))

            try:
                stdout = self._decode_logs(container.logs(stdout=True, stderr=False))
                stderr = self._decode_logs(container.logs(stdout=False, stderr=True))
            except DockerException as exc:
                raise SandboxExecutionError(
                    "Failed to collect Python sandbox output."
                ) from exc

            try:
                container.reload()
                final_state = (container.attrs or {}).get("State", {})
                if final_state.get("ExitCode") is not None:
                    exit_code = int(final_state["ExitCode"])
                oom_killed = bool(final_state.get("OOMKilled", oom_killed))
            except (DockerException, TypeError, ValueError):
                pass

            if timed_out:
                status = "timed_out"
            elif oom_killed:
                status = "oom_killed"
            else:
                status = "succeeded" if exit_code == 0 else "failed"

            return SandboxExecutionResult(
                sandbox_id=request.sandbox_id,
                status=status,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
                timed_out=timed_out,
                oom_killed=oom_killed,
                runtime="docker",
                image=self.image,
            )
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except NotFound:
                    pass
                except DockerException as exc:
                    cleanup_error = SandboxCleanupError(
                        "Failed to remove the Python sandbox container."
                    )
                    if primary_error is not None:
                        cleanup_error.add_note(
                            f"Original sandbox failure: {type(primary_error).__name__}."
                        )
                    raise cleanup_error from exc

    @staticmethod
    def _decode_logs(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
