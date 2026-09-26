"""One-shot Docker runtime for untrusted Python code."""

from __future__ import annotations

import ipaddress
import queue
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from threading import Event
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.types import LogConfig, Ulimit

from backend.sandbox.environment import build_sandbox_environment
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
from backend.sandbox.network_proxy import build_proxy_server_code
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

    def close(self) -> None:
        """Release the lazily created Docker API client owned by this runtime."""

        if self._client_was_provided:
            return
        client = self._client
        self._client = None
        if client is not None:
            client.close()

    def cancel(self, sandbox_id: str) -> bool:
        """Kill the named in-flight container without creating a new client."""

        if not self._client or not re.fullmatch(r"sb_[a-f0-9]{32}", sandbox_id):
            return False
        try:
            container = self._client.containers.get(f"aitrans-sb-{sandbox_id}")
            container.reload()
            state = (container.attrs or {}).get("State", {})
            if str(state.get("Status", "")).lower() != "running":
                return False
            container.kill()
            return True
        except NotFound:
            return False
        except DockerException:
            return False

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
        on_stage: Callable[[str, str, str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> SandboxExecutionResult:
        self._ensure_ready()
        if cancel_event is not None and cancel_event.is_set():
            return self._result_cancelled(request)
        client = self._get_client()
        container_name = f"aitrans-sb-{request.sandbox_id}"
        container = None
        proxy_container = None
        proxy_network = None
        proxy_address = ""
        output_client = None
        owns_output_client = False
        output_stream = None
        reader_thread: threading.Thread | None = None
        stop_reader = threading.Event()
        reader_done = threading.Event()
        output_queue: queue.Queue[Any] = queue.Queue(maxsize=32)
        started_at = time.monotonic()
        timed_out = False
        cancelled = False
        output_limit_exceeded = False
        exit_code: int | None = None
        oom_killed = False
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        primary_error: BaseException | None = None
        active_stage = ""

        try:
            if request.network_policy.mode == "restricted":
                self._emit_stage(
                    on_stage,
                    "network",
                    "running",
                    "Starting an isolated exact-host egress proxy.",
                )
                proxy_network, proxy_container, proxy_address = (
                    self._start_restricted_proxy(client, request)
                )
                self._emit_stage(
                    on_stage,
                    "network",
                    "complete",
                    "Restricted egress proxy is ready.",
                )
            self._emit_stage(
                on_stage, "create", "running", "Creating isolated Docker container."
            )
            active_stage = "create"
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
                    network_mode=(
                        str(proxy_network.name)
                        if proxy_network is not None
                        else self.policy.network_mode
                    ),
                    environment=build_sandbox_environment(
                        proxy_address=proxy_address or None
                    ),
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
                self._emit_stage(
                    on_stage, "create", "failed", "Docker container creation failed."
                )
                active_stage = ""
                raise SandboxCreateError(
                    "Failed to create the Python sandbox container."
                ) from exc
            self._emit_stage(
                on_stage, "create", "complete", "Isolated Docker container created."
            )
            active_stage = ""

            if cancel_event is not None and cancel_event.is_set():
                self._emit_stage(
                    on_stage,
                    "start",
                    "skipped",
                    "Run cancelled before container start.",
                )
                self._emit_stage(
                    on_stage,
                    "execute",
                    "skipped",
                    "Run cancelled before Python execution.",
                )
                return self._result_cancelled(request)

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

            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                self._emit_stage(
                    on_stage,
                    "start",
                    "skipped",
                    "Run cancelled before container start.",
                )
                self._emit_stage(
                    on_stage,
                    "execute",
                    "skipped",
                    "Run cancelled before Python execution.",
                )
                return self._result_cancelled(request)

            self._emit_stage(
                on_stage, "start", "running", "Starting isolated container."
            )
            active_stage = "start"
            try:
                container.start()
            except DockerException as exc:
                self._emit_stage(on_stage, "start", "failed", "Container start failed.")
                active_stage = ""
                raise SandboxStartError(
                    "Failed to start the Python sandbox container."
                ) from exc
            self._emit_stage(on_stage, "start", "complete", "Container started.")
            active_stage = ""
            self._emit_stage(
                on_stage,
                "execute",
                "running",
                "Running Python in the isolated container.",
            )
            active_stage = "execute"

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
                    cancel_event is not None
                    and cancel_event.is_set()
                    and not container_finished
                    and kill_deadline is None
                ):
                    cancelled = True
                    self._stop_output_reader(
                        output_stream,
                        reader_thread,
                        stop_reader,
                    )
                    output_stream = None
                    self._kill(container)
                    kill_deadline = now + self.docker_api_timeout_seconds
                    drain_deadline = kill_deadline
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
            self._emit_stage(
                on_stage,
                "execute",
                "complete",
                "Python execution stopped after cancellation."
                if cancelled
                else "Python execution finished.",
            )
            active_stage = ""

            if cancelled:
                status = "cancelled"
            elif output_limit_exceeded:
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
            if active_stage:
                self._emit_stage(
                    on_stage, active_stage, "failed", "Sandbox runtime stage failed."
                )
            raise
        finally:
            cleanup_error: SandboxCleanupError | None = None
            cleanup_cause: DockerException | None = None
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
                    cleanup_cause = exc
            if proxy_container is not None:
                try:
                    proxy_container.remove(force=True)
                except NotFound:
                    pass
                except DockerException as exc:
                    if cleanup_error is None:
                        cleanup_error = SandboxCleanupError(
                            "Failed to remove the sandbox egress proxy."
                        )
                        cleanup_cause = exc
            if proxy_network is not None:
                try:
                    proxy_network.remove()
                except NotFound:
                    pass
                except DockerException as exc:
                    if cleanup_error is None:
                        cleanup_error = SandboxCleanupError(
                            "Failed to remove the sandbox egress network."
                        )
                        cleanup_cause = exc
            if cleanup_error is not None:
                if primary_error is not None:
                    cleanup_error.add_note(
                        f"Original sandbox failure: {type(primary_error).__name__}."
                    )
                raise cleanup_error from cleanup_cause

    def _start_restricted_proxy(
        self,
        client: Any,
        request: SandboxExecutionRequest,
    ) -> tuple[Any, Any, str]:
        network = None
        proxy = None
        network_name = f"aitrans-egress-{request.sandbox_id}"
        proxy_name = f"aitrans-proxy-{request.sandbox_id}"
        try:
            network = client.networks.create(
                name=network_name,
                driver="bridge",
                internal=True,
                labels={
                    SANDBOX_LABEL: "true",
                    SANDBOX_ID_LABEL: request.sandbox_id,
                    RUNTIME_LABEL: "egress_network",
                },
            )
            proxy = client.containers.create(
                image=self.image,
                command=[
                    "python",
                    "-c",
                    build_proxy_server_code(request.network_policy),
                ],
                name=proxy_name,
                labels={
                    SANDBOX_LABEL: "true",
                    SANDBOX_ID_LABEL: request.sandbox_id,
                    RUNTIME_LABEL: "egress_proxy",
                },
                network_mode="bridge",
                environment=build_sandbox_environment(),
                user=self.policy.user,
                read_only=self.policy.read_only_rootfs,
                cap_drop=list(self.policy.cap_drop),
                security_opt=["no-new-privileges"],
                privileged=False,
                nano_cpus=min(self.policy.nano_cpus, 250_000_000),
                mem_limit=min(self.policy.memory_limit_bytes, 128 * 1024 * 1024),
                memswap_limit=min(self.policy.memory_limit_bytes, 128 * 1024 * 1024),
                pids_limit=min(self.policy.pids_limit, 32),
                ulimits=[
                    Ulimit(
                        name="nofile",
                        soft=min(self.policy.nofile_limit, 128),
                        hard=min(self.policy.nofile_limit, 128),
                    )
                ],
                tmpfs={"/tmp": self.policy.tmpfs_options},
                log_config=LogConfig(
                    type="json-file",
                    config={"max-size": "1m", "max-file": "1"},
                ),
                detach=True,
                stdin_open=False,
                tty=False,
            )
            proxy.start()
            network.connect(proxy)
            proxy.reload()
            networks = (
                (proxy.attrs or {}).get("NetworkSettings", {}).get("Networks", {})
            )
            details = networks.get(network_name, {})
            address = str(details.get("IPAddress", "") or "")
            parsed_address = ipaddress.ip_address(address)
            if (
                parsed_address.version != 4
                or not parsed_address.is_private
                or parsed_address.is_unspecified
                or parsed_address.is_loopback
                or parsed_address.is_link_local
                or parsed_address.is_multicast
            ):
                raise SandboxCreateError(
                    "Restricted proxy received an invalid internal network address."
                )
            return network, proxy, address
        except SandboxCreateError:
            raise
        except DockerException as exc:
            if proxy is not None:
                with suppress(DockerException):
                    proxy.remove(force=True)
            if network is not None:
                with suppress(DockerException):
                    network.remove()
            raise SandboxCreateError(
                "Failed to start the restricted sandbox egress proxy."
            ) from exc
        except (AttributeError, KeyError, ValueError) as exc:
            if proxy is not None:
                with suppress(DockerException):
                    proxy.remove(force=True)
            if network is not None:
                with suppress(DockerException):
                    network.remove()
            raise SandboxCreateError(
                "Restricted sandbox egress proxy could not be configured safely."
            ) from exc

    @staticmethod
    def _result_cancelled(request: SandboxExecutionRequest) -> SandboxExecutionResult:
        return SandboxExecutionResult(
            sandbox_id=request.sandbox_id,
            status="cancelled",
            duration_ms=0,
            runtime="docker",
        )

    @staticmethod
    def _emit_stage(
        callback: Callable[[str, str, str], None] | None,
        key: str,
        status: str,
        note: str,
    ) -> None:
        if callback is not None:
            callback(key, status, note)

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
