"""Host-side staging and output promotion for disposable sandboxes."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from app.infrastructure.paths import data_root
from backend.sandbox.errors import (
    SandboxCleanupError,
    SandboxCreateError,
    SandboxExecutionError,
    SandboxInvalidInputError,
    SandboxOutputLimitError,
)
from backend.sandbox.models import SandboxOutputFile
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY, SandboxPolicy

_SANDBOX_ID = re.compile(r"^sb_[a-f0-9]{32}$")
_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_INVALID_FILENAME_CHARACTERS = set('<>:"/\\|?*')
MAX_SANDBOX_INPUT_FILES = 64
MAX_SANDBOX_INPUT_FILE_BYTES = 20 * 1024 * 1024
MAX_SANDBOX_TOTAL_INPUT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SandboxInputFile:
    """Trusted backend reference to an input file; never planner supplied."""

    file_id: str
    display_name: str
    source_path: Path
    relative_path: str = ""
    expected_size_bytes: int | None = None
    expected_sha256: str = ""
    expected_mode: int | None = None


@dataclass(frozen=True, slots=True)
class SandboxWorkspace:
    sandbox_id: str
    root: Path
    input_dir: Path
    workspace_dir: Path
    output_dir: Path


def docker_volume_bindings(workspace: SandboxWorkspace) -> dict[str, dict[str, str]]:
    """Build the only Docker bind mapping used by the sandbox runtime."""

    expected_root = workspace.root.parent / workspace.sandbox_id
    if (
        not _SANDBOX_ID.fullmatch(workspace.sandbox_id)
        or workspace.root != expected_root
        or workspace.root.is_symlink()
        or workspace.input_dir != expected_root / "input"
        or workspace.workspace_dir != expected_root / "workspace"
        or workspace.output_dir != expected_root / "output"
    ):
        raise SandboxCreateError("Sandbox workspace directory is unavailable.")

    try:
        resolved_root = workspace.root.resolve(strict=True)
    except OSError as exc:
        raise SandboxCreateError("Sandbox workspace directory is unavailable.") from exc

    bindings: dict[str, dict[str, str]] = {}
    for host_path, container_path, mode in (
        (workspace.input_dir, "/input", "ro"),
        (workspace.workspace_dir, "/workspace", "rw"),
        (workspace.output_dir, "/output", "rw"),
    ):
        if host_path.is_symlink() or not host_path.is_dir():
            raise SandboxCreateError("Sandbox workspace directory is unavailable.")
        resolved = host_path.resolve(strict=True)
        if resolved.parent != resolved_root:
            raise SandboxCreateError("Sandbox workspace directory is unavailable.")
        bindings[str(resolved)] = {"bind": container_path, "mode": mode}
    return bindings


class SandboxWorkspaceManager:
    """Create isolated workspaces, stage inputs, and promote safe outputs."""

    def __init__(
        self,
        *,
        sandbox_root: str | Path | None = None,
        artifact_root: str | Path | None = None,
        policy: SandboxPolicy = DEFAULT_SANDBOX_POLICY,
    ) -> None:
        runtime_root = data_root() / "runtime"
        self.sandbox_root = (
            Path(
                sandbox_root if sandbox_root is not None else runtime_root / "sandboxes"
            )
            .expanduser()
            .resolve()
        )
        self.artifact_root = (
            Path(
                artifact_root
                if artifact_root is not None
                else runtime_root / "sandbox_artifacts"
            )
            .expanduser()
            .resolve()
        )
        self.policy = policy
        if (
            self.sandbox_root == self.artifact_root
            or self.sandbox_root in self.artifact_root.parents
            or self.artifact_root in self.sandbox_root.parents
        ):
            raise ValueError("Sandbox and artifact roots must be separate directories.")

    def create(self, sandbox_id: str) -> SandboxWorkspace:
        if not _SANDBOX_ID.fullmatch(sandbox_id):
            raise SandboxInvalidInputError("Sandbox identifier is invalid.")
        root = self.sandbox_root / sandbox_id
        created_root = False
        try:
            self.sandbox_root.mkdir(parents=True, exist_ok=True)
            root.mkdir(mode=0o700, exist_ok=False)
            created_root = True
            input_dir = root / "input"
            workspace_dir = root / "workspace"
            output_dir = root / "output"
            input_dir.mkdir(mode=0o755)
            workspace_dir.mkdir(mode=0o777)
            output_dir.mkdir(mode=0o777)
            input_dir.chmod(0o755)
            workspace_dir.chmod(0o777)
            output_dir.chmod(0o777)
            return SandboxWorkspace(
                sandbox_id=sandbox_id,
                root=root,
                input_dir=input_dir,
                workspace_dir=workspace_dir,
                output_dir=output_dir,
            )
        except SandboxInvalidInputError:
            raise
        except OSError as exc:
            if created_root:
                shutil.rmtree(root, ignore_errors=True)
            raise SandboxCreateError(
                "Failed to create an isolated sandbox workspace."
            ) from exc

    def stage_input(
        self,
        workspace: SandboxWorkspace,
        input_file: SandboxInputFile,
        *,
        max_bytes: int | None = None,
    ) -> Path:
        self._assert_workspace(workspace)
        if not _FILE_ID.fullmatch(str(input_file.file_id or "")):
            raise SandboxInvalidInputError("Sandbox input file identifier is invalid.")
        display_name = self._safe_filename(input_file.display_name)
        relative_path = self._safe_relative_path(
            input_file.relative_path or display_name
        )
        source_path = Path(input_file.source_path).expanduser()
        allowed_bytes = min(
            MAX_SANDBOX_INPUT_FILE_BYTES,
            MAX_SANDBOX_INPUT_FILE_BYTES if max_bytes is None else max(0, int(max_bytes)),
        )
        try:
            source_stat = source_path.lstat()
            if not stat.S_ISREG(source_stat.st_mode):
                raise SandboxInvalidInputError(
                    "Sandbox inputs must be regular files, not links or devices."
                )
            if source_stat.st_size > allowed_bytes:
                raise SandboxInvalidInputError(
                    "A sandbox input file exceeds the input size limit."
                )
            source = source_path.resolve(strict=True)
            destination = workspace.input_dir.joinpath(*relative_path.parts)
            self._assert_contained(destination, workspace.input_dir)
            if destination.exists() or destination.is_symlink():
                raise SandboxInvalidInputError(
                    "Sandbox input filenames must be unique."
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._copy_input_hash(
                source,
                destination,
                max_bytes=allowed_bytes,
                expected_size_bytes=input_file.expected_size_bytes,
                expected_sha256=input_file.expected_sha256,
            )
            copied_stat = destination.lstat()
            if not stat.S_ISREG(copied_stat.st_mode):
                raise SandboxInvalidInputError(
                    "Sandbox inputs must be regular files, not links or devices."
                )
            destination.chmod(0o444)
            return destination
        except SandboxInvalidInputError:
            raise
        except (OSError, RuntimeError) as exc:
            raise SandboxInvalidInputError(
                "Sandbox input file could not be staged."
            ) from exc

    def write_code(self, workspace: SandboxWorkspace, code: str) -> Path:
        self._assert_workspace(workspace)
        code_path = workspace.workspace_dir / "main.py"
        try:
            self._assert_contained(code_path, workspace.workspace_dir)
            with code_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(code)
            code_path.chmod(0o444)
            return code_path
        except OSError as exc:
            raise SandboxCreateError(
                "Failed to prepare Python code for sandbox execution."
            ) from exc

    def copy_inputs_to_workspace(
        self,
        workspace: SandboxWorkspace,
        input_files: tuple[SandboxInputFile, ...],
    ) -> None:
        """Copy staged, read-only inputs into the editable working directory."""

        self._assert_workspace(workspace)
        for input_file in input_files:
            relative_path = self._safe_relative_path(
                input_file.relative_path or input_file.display_name
            )
            source = workspace.input_dir.joinpath(*relative_path.parts)
            destination = workspace.workspace_dir.joinpath(*relative_path.parts)
            self._assert_contained(source, workspace.input_dir)
            self._assert_contained(destination, workspace.workspace_dir)
            try:
                source_stat = source.lstat()
                if not stat.S_ISREG(source_stat.st_mode):
                    raise SandboxInvalidInputError(
                        "Sandbox inputs must be regular files, not links or devices."
                    )
                if destination.exists() or destination.is_symlink():
                    raise SandboxInvalidInputError(
                        "Sandbox working-copy filenames must be unique."
                    )
                self._make_safe_directories(destination.parent, workspace.workspace_dir)
                size_bytes, digest = self._copy_input_hash(
                    source,
                    destination,
                    max_bytes=MAX_SANDBOX_INPUT_FILE_BYTES,
                    expected_size_bytes=input_file.expected_size_bytes,
                    expected_sha256=input_file.expected_sha256,
                )
                if size_bytes != source_stat.st_size or digest != self._sha256(source):
                    raise SandboxInvalidInputError(
                        "A staged sandbox input changed before working-copy creation."
                    )
                original_mode = (
                    input_file.expected_mode
                    if input_file.expected_mode is not None
                    else stat.S_IMODE(source_stat.st_mode)
                )
                destination.chmod(0o666 | (original_mode & 0o111))
            except SandboxInvalidInputError:
                raise
            except (OSError, RuntimeError) as exc:
                raise SandboxInvalidInputError(
                    "Sandbox working copy could not be prepared safely."
                ) from exc

    def collect_outputs(
        self,
        workspace: SandboxWorkspace,
    ) -> list[SandboxOutputFile]:
        self._assert_workspace(workspace)
        output_root = workspace.output_dir.resolve(strict=True)
        candidates: list[tuple[Path, PurePosixPath]] = []
        total_output_bytes = 0

        def scan(directory: Path, relative: PurePosixPath) -> None:
            nonlocal total_output_bytes
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
                for entry in entries:
                    name = self._safe_filename(entry.name)
                    child_relative = relative / name
                    child = Path(entry.path)
                    metadata = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(metadata.st_mode):
                        self._assert_contained(child, output_root)
                        scan(child, child_relative)
                    elif stat.S_ISREG(metadata.st_mode):
                        if metadata.st_size > self.policy.max_output_file_bytes:
                            raise SandboxOutputLimitError(
                                "A sandbox output file exceeds the size limit."
                            )
                        total_output_bytes += metadata.st_size
                        if total_output_bytes > self.policy.max_total_output_bytes:
                            raise SandboxOutputLimitError(
                                "Sandbox outputs exceed the total size limit."
                            )
                        if len(candidates) >= self.policy.max_output_files:
                            raise SandboxOutputLimitError(
                                "Sandbox produced too many output files."
                            )
                        resolved = child.resolve(strict=True)
                        self._assert_contained(resolved, output_root)
                        candidates.append((resolved, child_relative))
                    else:
                        raise SandboxExecutionError(
                            "Sandbox output contains a link or unsupported file."
                        )
            except (SandboxExecutionError, SandboxOutputLimitError):
                raise
            except (OSError, RuntimeError) as exc:
                raise SandboxExecutionError(
                    "Sandbox output could not be inspected safely."
                ) from exc

        scan(output_root, PurePosixPath())
        promoted: list[SandboxOutputFile] = []
        artifact_sandbox_root = self.artifact_root / workspace.sandbox_id
        created_artifact_root = False
        try:
            artifact_sandbox_root.mkdir(parents=True, mode=0o700, exist_ok=False)
            created_artifact_root = True
            for source, relative_path in candidates:
                destination = artifact_sandbox_root.joinpath(*relative_path.parts)
                self._assert_contained(destination, artifact_sandbox_root)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                remaining_bytes = self.policy.max_total_output_bytes - sum(
                    item.size_bytes for item in promoted
                )
                size_bytes, digest = self._copy_hash(
                    source,
                    destination,
                    max_bytes=min(
                        self.policy.max_output_file_bytes,
                        remaining_bytes,
                    ),
                )
                promoted.append(
                    SandboxOutputFile(
                        file_id=f"sbo_{uuid4().hex}",
                        relative_path=relative_path.as_posix(),
                        size_bytes=size_bytes,
                        sha256=digest,
                    )
                )
        except (SandboxExecutionError, SandboxOutputLimitError):
            if created_artifact_root:
                shutil.rmtree(artifact_sandbox_root, ignore_errors=True)
            raise
        except OSError as exc:
            if created_artifact_root:
                shutil.rmtree(artifact_sandbox_root, ignore_errors=True)
            raise SandboxExecutionError(
                "Sandbox output could not be promoted safely."
            ) from exc
        return promoted

    def cleanup(self, workspace: SandboxWorkspace) -> None:
        if not workspace.root.exists() and not workspace.root.is_symlink():
            return
        self._assert_workspace(workspace)

        def retry_readonly(
            function,
            path: str,
            error_info: tuple[type[BaseException], BaseException, object],
        ) -> None:
            del error_info
            candidate = Path(path)
            try:
                candidate.absolute().relative_to(workspace.root.absolute())
            except ValueError as exc:
                raise SandboxCleanupError(
                    "Sandbox cleanup attempted to leave its workspace."
                ) from exc
            if candidate.is_symlink():
                function(path)
                return
            mode = candidate.lstat().st_mode
            writable_mode = stat.S_IREAD | stat.S_IWRITE
            if stat.S_ISDIR(mode):
                writable_mode |= stat.S_IEXEC
            os.chmod(path, writable_mode)
            function(path)

        try:
            shutil.rmtree(workspace.root, onerror=retry_readonly)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SandboxCleanupError(
                "Failed to remove the temporary sandbox workspace."
            ) from exc

    def _assert_workspace(self, workspace: SandboxWorkspace) -> None:
        expected = self.sandbox_root / workspace.sandbox_id
        if (
            not _SANDBOX_ID.fullmatch(workspace.sandbox_id)
            or workspace.root != expected
            or workspace.root.is_symlink()
            or workspace.input_dir != expected / "input"
            or workspace.workspace_dir != expected / "workspace"
            or workspace.output_dir != expected / "output"
        ):
            raise SandboxInvalidInputError("Sandbox workspace is invalid.")
        try:
            resolved_root = workspace.root.resolve(strict=True)
        except OSError as exc:
            raise SandboxInvalidInputError("Sandbox workspace is unavailable.") from exc
        self._assert_contained(resolved_root, self.sandbox_root)
        if resolved_root != workspace.root:
            raise SandboxInvalidInputError("Sandbox workspace is invalid.")

    @staticmethod
    def _safe_filename(name: str) -> str:
        candidate = str(name or "")
        if (
            not candidate
            or candidate in {".", ".."}
            or len(candidate) > 255
            or candidate.endswith((" ", "."))
            or any(
                ord(character) < 32 or character in _INVALID_FILENAME_CHARACTERS
                for character in candidate
            )
            or PurePosixPath(candidate).name != candidate
            or PureWindowsPath(candidate).name != candidate
        ):
            raise SandboxInvalidInputError("Sandbox filename is invalid.")
        stem = candidate.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise SandboxInvalidInputError("Sandbox filename is invalid.")
        return candidate

    @classmethod
    def _safe_relative_path(cls, value: str) -> PurePosixPath:
        raw = str(value or "").replace("\\", "/")
        relative = PurePosixPath(raw)
        if (
            not raw
            or len(raw) > 1024
            or relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise SandboxInvalidInputError("Sandbox input path is invalid.")
        for part in relative.parts:
            cls._safe_filename(part)
        return relative

    @staticmethod
    def _copy_input_hash(
        source: Path,
        destination: Path,
        *,
        max_bytes: int,
        expected_size_bytes: int | None,
        expected_sha256: str,
    ) -> tuple[int, str]:
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with source.open("rb") as source_handle, temporary.open("xb") as target:
                while chunk := source_handle.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise SandboxInvalidInputError(
                            "A sandbox input file exceeds the input size limit."
                        )
                    digest.update(chunk)
                    target.write(chunk)
            calculated_digest = digest.hexdigest()
            if (
                expected_size_bytes is not None
                and size_bytes != expected_size_bytes
            ) or (expected_sha256 and calculated_digest != expected_sha256):
                raise SandboxInvalidInputError(
                    "A sandbox input changed while it was being staged."
                )
            os.replace(temporary, destination)
            return size_bytes, calculated_digest
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _assert_contained(path: Path, parent: Path) -> None:
        resolved_path = path.resolve(strict=False)
        resolved_parent = parent.resolve(strict=False)
        if (
            resolved_path != resolved_parent
            and resolved_parent not in resolved_path.parents
        ):
            raise SandboxInvalidInputError(
                "Sandbox path is outside its allowed directory."
            )

    @staticmethod
    def _copy_hash(
        source: Path,
        destination: Path,
        *,
        max_bytes: int,
    ) -> tuple[int, str]:
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with source.open("rb") as source_handle, temporary.open("xb") as target:
                while chunk := source_handle.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise SandboxOutputLimitError(
                            "Sandbox output changed beyond its allowed size."
                        )
                    digest.update(chunk)
                    target.write(chunk)
            os.replace(temporary, destination)
        except SandboxOutputLimitError:
            temporary.unlink(missing_ok=True)
            raise
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        return size_bytes, digest.hexdigest()

    @classmethod
    def _make_safe_directories(cls, directory: Path, root: Path) -> None:
        current = root
        for part in directory.relative_to(root).parts:
            current = current / part
            cls._assert_contained(current, root)
            if current.is_symlink():
                raise SandboxInvalidInputError(
                    "Sandbox working-copy paths must not contain symbolic links."
                )
            current.mkdir(mode=0o777, exist_ok=True)
            if not current.is_dir():
                raise SandboxInvalidInputError(
                    "Sandbox working-copy path is not a directory."
                )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
