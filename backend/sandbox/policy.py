"""Fixed V1 sandbox security and resource policy."""

from __future__ import annotations

from dataclasses import dataclass

_MIB = 1024 * 1024
_MAX_TIMEOUT_SECONDS = 30.0
_MAX_CPU_NANO_CORES = 1_000_000_000
_MAX_MEMORY_BYTES = 512 * _MIB
_MAX_PIDS = 64
_MAX_NOFILE = 256
_MAX_TMPFS_BYTES = 64 * _MIB
_MAX_STREAM_BYTES = 1 * _MIB
_MAX_OUTPUT_FILES = 64
_MAX_OUTPUT_FILE_BYTES = 20 * _MIB
_MAX_TOTAL_OUTPUT_BYTES = 50 * _MIB
MAX_WORKSPACE_CHANGED_FILES = 50
MAX_WORKSPACE_CHANGED_FILE_BYTES = 5 * _MIB
MAX_WORKSPACE_TOTAL_CHANGED_BYTES = 20 * _MIB


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """System-owned sandbox limits. Callers may tighten but never relax them."""

    network_mode: str = "none"
    user: str = "10001:10001"
    read_only_rootfs: bool = True
    cap_drop: tuple[str, ...] = ("ALL",)
    no_new_privileges: bool = True
    nano_cpus: int = _MAX_CPU_NANO_CORES
    memory_limit_bytes: int = _MAX_MEMORY_BYTES
    memory_swap_limit_bytes: int = _MAX_MEMORY_BYTES
    pids_limit: int = _MAX_PIDS
    nofile_limit: int = _MAX_NOFILE
    tmpfs_size_bytes: int = _MAX_TMPFS_BYTES
    timeout_seconds: float = _MAX_TIMEOUT_SECONDS
    stdout_limit_bytes: int = _MAX_STREAM_BYTES
    stderr_limit_bytes: int = _MAX_STREAM_BYTES
    max_output_files: int = _MAX_OUTPUT_FILES
    max_output_file_bytes: int = _MAX_OUTPUT_FILE_BYTES
    max_total_output_bytes: int = _MAX_TOTAL_OUTPUT_BYTES

    def __post_init__(self) -> None:
        if self.network_mode != "none":
            raise ValueError("Sandbox network access must remain disabled.")
        if self.user != "10001:10001":
            raise ValueError("Sandbox processes must run as UID/GID 10001.")
        if not self.read_only_rootfs:
            raise ValueError("Sandbox root filesystem must remain read-only.")
        if self.cap_drop != ("ALL",):
            raise ValueError("Sandbox must drop all Linux capabilities.")
        if not self.no_new_privileges:
            raise ValueError("Sandbox must disable privilege escalation.")
        if not 0 < self.nano_cpus <= _MAX_CPU_NANO_CORES:
            raise ValueError("Sandbox CPU limit exceeds the fixed policy.")
        if not 0 < self.memory_limit_bytes <= _MAX_MEMORY_BYTES:
            raise ValueError("Sandbox memory limit exceeds the fixed policy.")
        if self.memory_swap_limit_bytes != self.memory_limit_bytes:
            raise ValueError("Sandbox swap must not exceed its memory limit.")
        if not 0 < self.pids_limit <= _MAX_PIDS:
            raise ValueError("Sandbox PID limit exceeds the fixed policy.")
        if not 16 <= self.nofile_limit <= _MAX_NOFILE:
            raise ValueError("Sandbox file descriptor limit exceeds the fixed policy.")
        if not 0 < self.tmpfs_size_bytes <= _MAX_TMPFS_BYTES:
            raise ValueError("Sandbox temporary storage exceeds the fixed policy.")
        if not 0 < self.timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise ValueError("Sandbox timeout exceeds the fixed policy.")
        if not 0 < self.stdout_limit_bytes <= _MAX_STREAM_BYTES:
            raise ValueError("Sandbox stdout limit exceeds the fixed policy.")
        if not 0 < self.stderr_limit_bytes <= _MAX_STREAM_BYTES:
            raise ValueError("Sandbox stderr limit exceeds the fixed policy.")
        if not 0 < self.max_output_files <= _MAX_OUTPUT_FILES:
            raise ValueError("Sandbox output file count exceeds the fixed policy.")
        if not 0 < self.max_output_file_bytes <= _MAX_OUTPUT_FILE_BYTES:
            raise ValueError("Sandbox output file size exceeds the fixed policy.")
        if not 0 < self.max_total_output_bytes <= _MAX_TOTAL_OUTPUT_BYTES:
            raise ValueError("Sandbox total output size exceeds the fixed policy.")

    @property
    def tmpfs_options(self) -> str:
        size_mib = max(1, self.tmpfs_size_bytes // _MIB)
        return f"rw,nosuid,nodev,size={size_mib}m,mode=1777"


DEFAULT_SANDBOX_POLICY = SandboxPolicy()
