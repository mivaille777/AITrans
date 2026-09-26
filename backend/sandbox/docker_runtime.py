"""One-shot Docker runtime for untrusted Python code."""

from __future__ import annotations

import queue
import threading
import time
from contextlib import suppress
from dataclasses import replace
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.types import LogConfig, Ulimit

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
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY, SandboxPolicy
from backend.sandbox.workspace import SandboxWorkspace, docker_volume_bindings

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
        policy: SandboxPolicy = DEFAULT_SANDBOX_POLICY,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 0.1,
        docker_api_timeout_seconds: int = 5,
        client: Any | None = None,
    ) -> None:
        if not image or image.strip().lower().endswith(":latest"):
            raise ValueError("A pinned sandbox image tag is required.")
        if timeout_seconds is not None:
            policy = replace(policy, timeout_seconds=timeout_seconds)
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive.")
        if docker_api_timeout_seconds <= 0:
            raise ValueError("docker_api_timeout_seconds must be positive.")

        self.image = image
        self.policy = policy
        self.timeout_seconds = policy.timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.docker_api_timeout_seconds = docker_api_timeout_seconds
        self._client = client
        self._client_was_provided = client is not None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = docker.from_env(timeout=self.docker_api_timeout_seconds)
            except DockerException as exc:
                raise DockerUnavailableError("Docker daemon is unavailable.") from exc
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
        *,
        workspace: SandboxWorkspace,
    ) -> SandboxExecutionResult:
        self._ensure_ready()
        client = self._get_client()
        container_name = f"aitrans-sb-{request.sandbox_id}"
        container = None
        output_client = None
        owns_output_client = False
        output_stream = None
        reader_thread: threading.Thread | None = None
        stop_reader = threading.Event()
        reader_done = threading.Event()
        output_queue: queue.Queue[Any] = queue.Queue(maxsize=32)
        started_at = time.monotonic()
        timed_out = False
        output_limit_exceeded = False
        exit_code: int | None = None
        oom_killed = False
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        primary_error: BaseException | None = None

        try:
            try:
                container = client.containers.create(
                    image=self.image,
                    command=["python", "/workspace/main.py"],
                    name=container_name,
                    labels={
                        SANDBOX_LABEL: "true",
                        SANDBOX_ID_LABEL: request.sandbox_id,
                        RUNTIME_LABEL: "python",
                    },
                    network_mode=self.policy.network_mode,
                    working_dir="/workspace",
                    volumes=docker_volume_bindings(workspace),
                    user=self.policy.user,
                    read_only=self.policy.read_only_rootfs,
                    cap_drop=list(self.policy.cap_drop),
                    security_opt=["no-new-privileges"],
                    privileged=False,
                    nano_cpus=self.policy.nano_cpus,
                    mem_limit=self.policy.memory_limit_bytes,
                    memswap_limit=self.policy.memory_swap_limit_bytes,
                    pids_limit=self.policy.pids_limit,
                    ulimits=[
                        Ulimit(
                            name="nofile",
                            soft=self.policy.nofile_limit,
                            hard=self.policy.nofile_limit,
                        )
                    ],
                    tmpfs={"/tmp": self.policy.tmpfs_options},
                    log_config=LogConfig(
                        type="json-file",
                        config={"max-size": "2m", "max-file": "1"},
                    ),
                    detach=True,
                    stdin_open=False,
                    tty=False,
                )
            except DockerException as exc:
                raise SandboxCreateError(
                    "Failed to create the Python sandbox container."
                ) from exc

            try:
                if self._client_was_provided:
                    output_container = container
                else:
                    output_client = docker.from_env(
                        timeout=max(
                            self.docker_api_timeout_seconds,
                            int(self.timeout_seconds + 5),
                        )
                    )
                    owns_output_client = True
                    output_container = output_client.containers.get(container.id)
                output_stream = output_container.attach(
                    stream=True,
                    logs=False,
                    demux=True,
                )
            except DockerException as exc:
                raise SandboxExecutionError(
                    "Failed to monitor Python sandbox output."
                ) from exc

            reader_thread = threading.Thread(
                target=self._pump_output,
                args=(output_stream, output_queue, stop_reader, reader_done),
                name=f"sandbox-output-{request.sandbox_id}",
                daemon=True,
            )
            reader_thread.start()

            try:
                container.start()
            except DockerException as exc:
                raise SandboxStartError(
                    "Failed to start the Python sandbox container."
                ) from exc

            deadline = time.monotonic() + self.timeout_seconds
            container_finished = False
            kill_deadline: float | None = None
            drain_deadline: float | None = None
            next_inspect_at = 0.0
            state: dict[str, Any] = {}

            while True:
                try:
                    frame = output_queue.get(timeout=self.poll_interval_seconds)
                except queue.Empty:
                    frame = None

                if isinstance(frame, BaseException):
                    if not container_finished and kill_deadline is None:
                        raise SandboxExecutionError(
                            "Failed while collecting Python sandbox output."
                        ) from frame
                elif frame is not None:
                    if not isinstance(frame, tuple) or len(frame) != 2:
                        raise SandboxExecutionError(
                            "Docker returned an invalid sandbox output frame."
                        )
                    stdout_chunk, stderr_chunk = frame
                    stdout_overflow = self._append_bounded(
                        stdout_buffer,
                        stdout_chunk,
                        self.policy.stdout_limit_bytes,
                    )
                    stderr_overflow = self._append_bounded(
                        stderr_buffer,
                        stderr_chunk,
                        self.policy.stderr_limit_bytes,
                    )
                    output_limit_exceeded = (
                        output_limit_exceeded or stdout_overflow or stderr_overflow
                    )

                now = time.monotonic()
                if now >= next_inspect_at or output_limit_exceeded:
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
                    state_status = str(state.get("Status", "")).lower()
                    container_finished = state_status not in {
                        "created",
                        "restarting",
                        "running",
                        "paused",
                    }
                    if container_finished:
                        if state.get("ExitCode") is not None:
                            exit_code = int(state["ExitCode"])
                        oom_killed = bool(state.get("OOMKilled", False))
                        if drain_deadline is None:
                            drain_deadline = (
                                time.monotonic() + self.docker_api_timeout_seconds
                            )
                    next_inspect_at = time.monotonic() + self.poll_interval_seconds

                now = time.monotonic()
                if (
                    not container_finished
                    and kill_deadline is None
                    and output_limit_exceeded
                ):
                    self._stop_output_reader(
                        output_stream,
                        reader_thread,
                        stop_reader,
                    )
                    output_stream = None
                    self._kill(container)
                    kill_deadline = now + self.docker_api_timeout_seconds
                    drain_deadline = kill_deadline
                elif (
                    not container_finished and kill_deadline is None and now >= deadline
                ):
                    timed_out = True
                    self._stop_output_reader(
                        output_stream,
                        reader_thread,
                        stop_reader,
                    )
                    output_stream = None
                    self._kill(container)
                    kill_deadline = now + self.docker_api_timeout_seconds
                    drain_deadline = kill_deadline

                if container_finished and reader_done.is_set() and output_queue.empty():
                    break
                if drain_deadline is not None and now >= drain_deadline:
                    break

            if state.get("ExitCode") is not None:
                exit_code = int(state["ExitCode"])
            oom_killed = bool(state.get("OOMKilled", oom_killed))

            if output_limit_exceeded:
                status = "output_limit_exceeded"
            elif timed_out:
                status = "timed_out"
            elif oom_killed:
                status = "oom_killed"
            else:
                status = "succeeded" if exit_code == 0 else "failed"

            return SandboxExecutionResult(
                sandbox_id=request.sandbox_id,
                status=status,
                exit_code=exit_code,
                stdout=self._decode_logs(bytes(stdout_buffer)),
                stderr=self._decode_logs(bytes(stderr_buffer)),
                duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
                timed_out=timed_out,
                output_limit_exceeded=output_limit_exceeded,
                oom_killed=oom_killed,
                stdout_bytes=len(stdout_buffer),
                stderr_bytes=len(stderr_buffer),
                runtime="docker",
                image=self.image,
            )
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            stop_reader.set()
            self._close_output_stream(output_stream)
            if reader_thread is not None:
                reader_thread.join(timeout=min(1.0, self.docker_api_timeout_seconds))
            if owns_output_client and output_client is not None:
                with suppress(DockerException, OSError):
                    output_client.close()
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

    def _kill(self, container: Any) -> None:
        try:
            container.kill()
        except NotFound:
            return
        except DockerException as exc:
            raise SandboxExecutionError(
                "Failed to stop the Python sandbox container."
            ) from exc

    @staticmethod
    def _append_bounded(
        destination: bytearray,
        chunk: bytes | None,
        limit: int,
    ) -> bool:
        if not chunk:
            return False
        remaining = max(0, limit - len(destination))
        destination.extend(chunk[:remaining])
        return len(chunk) > remaining

    @staticmethod
    def _pump_output(
        stream: Any,
        output_queue: queue.Queue[Any],
        stop_reader: threading.Event,
        reader_done: threading.Event,
    ) -> None:
        try:
            for frame in stream:
                while not stop_reader.is_set():
                    try:
                        output_queue.put(frame, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:  # noqa: BLE001 - Docker streams may raise transport/parser errors.
            while not stop_reader.is_set():
                try:
                    output_queue.put(exc, timeout=0.1)
                    break
                except queue.Full:
                    continue
        finally:
            reader_done.set()

    @staticmethod
    def _close_output_stream(stream: Any | None) -> None:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except (DockerException, OSError):
                # Closing the stream is best-effort; container removal is authoritative.
                return

    def _stop_output_reader(
        self,
        stream: Any | None,
        reader_thread: threading.Thread | None,
        stop_reader: threading.Event,
    ) -> None:
        stop_reader.set()
        self._close_output_stream(stream)
        if reader_thread is not None:
            reader_thread.join(timeout=min(1.0, self.docker_api_timeout_seconds))

    @staticmethod
    def _decode_logs(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
