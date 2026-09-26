"""Approval-gated, conflict-aware writes from sandbox changesets to host workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.infrastructure.paths import data_root
from backend.models.sandbox_approval import (
    PermissionGrant,
    SandboxApprovalChange,
    SandboxApprovalRequest,
)
from backend.models.sandbox_permissions import ExecutionPolicy, PermissionRequest
from backend.sandbox.permissions import PermissionPolicyEngine
from backend.sandbox.policy import (
    MAX_WORKSPACE_CHANGED_FILE_BYTES,
    MAX_WORKSPACE_CHANGED_FILES,
    MAX_WORKSPACE_TOTAL_CHANGED_BYTES,
)
from backend.sandbox.workspace_snapshot import (
    WorkspaceChange,
    WorkspaceChangeSet,
    WorkspaceSnapshotFile,
    calculate_changeset_hash,
    create_workspace_snapshot,
    is_protected_workspace_path,
)
from backend.services.filesystem_workspace_service import (
    FilesystemWorkspaceError,
    FilesystemWorkspaceService,
)
from backend.services.sandbox_approval_service import (
    SandboxApprovalError,
    SandboxApprovalService,
)

_SANDBOX_ID = re.compile(r"^sb_[a-f0-9]{32}$")
_MAX_AUDIT_ROWS = 2000
_DEFAULT_AUDIT_DATABASE = (
    data_root() / "runtime" / "sandbox_workspace_apply_audit.sqlite3"
)


class WorkspaceApplyError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class WorkspaceApplyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkspaceApplyResult(WorkspaceApplyModel):
    audit_id: str
    changeset_hash: str
    workspace_id: str
    status: Literal["applied"] = "applied"
    applied_changes: tuple[WorkspaceChange, ...]


class WorkspaceApplyAuditRecord(WorkspaceApplyModel):
    audit_id: str
    created_at: datetime
    workspace_id: str
    changeset_hash: str
    status: str
    change_count: int = Field(ge=0)
    changed_paths: tuple[str, ...]
    error_code: str = ""


class WorkspaceApplyService:
    """Apply one approved changeset; host paths and patch payloads stay server-side."""

    def __init__(
        self,
        filesystem_workspace_service: FilesystemWorkspaceService,
        approval_service: SandboxApprovalService,
        *,
        change_store_root: str | Path | None = None,
        audit_database_path: str | Path | None = None,
        permission_policy_engine: PermissionPolicyEngine | None = None,
        debug_service: object | None = None,
    ) -> None:
        self.filesystem_workspace_service = filesystem_workspace_service
        self.approval_service = approval_service
        self.change_store_root = (
            Path(
                change_store_root
                if change_store_root is not None
                else data_root() / "runtime" / "sandbox_artifacts" / "workspace_changes"
            )
            .expanduser()
            .resolve()
        )
        self.audit_database_path = (
            Path(
                audit_database_path
                if audit_database_path is not None
                else _DEFAULT_AUDIT_DATABASE
            )
            .expanduser()
            .resolve()
        )
        self._policy_engine = permission_policy_engine or PermissionPolicyEngine()
        self._debug_service = debug_service
        self._lock = RLock()
        self._initialize_audit_store()

    def request_approval(
        self,
        changeset: WorkspaceChangeSet,
    ) -> SandboxApprovalRequest:
        """Create a user decision tied to this exact workspace diff."""

        changeset = self._validate_changeset(changeset)
        if not changeset.changes:
            raise WorkspaceApplyError(
                "workspace_changeset_empty",
                "There are no workspace changes to apply.",
                status_code=400,
            )
        self._load_payloads(changeset)
        self._assert_base_is_current(changeset)
        run_id = f"run_{uuid4().hex}"
        tool_call_id = f"tool_{uuid4().hex}"
        if self._debug_service is not None:
            try:
                trace = self._debug_service.get_run(changeset.sandbox_id)
                run_id = trace.run.run_id
                tool_call_id = trace.run.tool_call_id or tool_call_id
            except Exception:  # noqa: BLE001, S110 - Trace is non-authoritative.
                pass
        target = changeset.changes[0].path
        self._record_trace_activity(
            changeset.sandbox_id,
            kind="policy",
            action="permission.request",
            target=target,
            decision="observed",
            reason="Request to apply sandbox changes to the selected host workspace.",
            permission_action="filesystem.apply_host",
            policy_rule="workspace_write.host_apply",
        )
        request = PermissionRequest(
            action="filesystem.apply_host",
            target=changeset.changeset_hash,
            reason=f"Apply {len(changeset.changes)} approved workspace change(s).",
            tool_name="workspace_apply",
            run_id=run_id,
            tool_call_id=tool_call_id,
        )
        policy = ExecutionPolicy(
            profile="workspace_write",
            workspace_id=changeset.workspace_id,
        )
        decision = self._policy_engine.evaluate(request, policy)
        if decision.decision != "approval_required":
            self._record_trace_activity(
                changeset.sandbox_id,
                kind="policy",
                action="permission.deny",
                target=target,
                decision="denied",
                reason=decision.reason,
                permission_action="filesystem.apply_host",
                policy_rule=decision.reason_code,
            )
            raise WorkspaceApplyError(
                "workspace_apply_denied",
                "The active permission policy does not allow host workspace apply.",
                status_code=403,
            )
        self._record_trace_activity(
            changeset.sandbox_id,
            kind="policy",
            action="permission.approval_required",
            target=target,
            decision="approval_required",
            reason=decision.reason,
            permission_action="filesystem.apply_host",
            policy_rule=decision.reason_code,
        )
        try:
            approval = self.approval_service.create_approval(
                request,
                decision,
                requested_changes=tuple(
                    SandboxApprovalChange(
                        operation=change.operation,
                        path=change.path,
                        size_before=change.size_before,
                        size_after=change.size_after,
                    )
                    for change in changeset.changes
                ),
            )
        except SandboxApprovalError as exc:
            raise self._approval_error(exc) from exc
        self._record_audit(changeset, "approval_requested")
        return approval

    def apply(
        self,
        changeset: WorkspaceChangeSet,
        *,
        approval_id: str,
    ) -> WorkspaceApplyResult:
        """Consume the exact one-time grant, then safely apply the stored payloads."""

        changeset = self._validate_changeset(changeset)
        if not changeset.changes:
            raise WorkspaceApplyError(
                "workspace_changeset_empty",
                "There are no workspace changes to apply.",
                status_code=400,
            )
        try:
            grant = self._consume_approval(changeset, approval_id)
        except WorkspaceApplyError as exc:
            self._record_trace_activity(
                changeset.sandbox_id,
                kind="file",
                action="filesystem.apply",
                target=changeset.changes[0].path,
                decision="denied",
                reason=exc.code,
                permission_action="filesystem.apply_host",
                policy_rule="workspace_write.host_apply",
                approval_id=approval_id,
            )
            self._record_trace_stage(
                changeset.sandbox_id, "apply", "failed", "Host apply was not authorized."
            )
            raise
        audit_id = self._record_audit(changeset, "applying")
        self._record_trace_stage(
            changeset.sandbox_id, "apply", "running", "Applying approved workspace changes."
        )
        try:
            payloads = self._load_payloads(changeset)
            root = self.filesystem_workspace_service.active_root_path(
                changeset.workspace_id
            )
            self._assert_base_is_current(changeset)
            for change in changeset.changes:
                self._assert_target_matches_base(root, change)

            created_directories: list[Path] = []
            for change in changeset.changes:
                target = self._target_path(root, change.path)
                if change.operation == "delete":
                    self._assert_target_matches_base(root, change)
                    target.unlink()
                    self._fsync_directory(target.parent)
                else:
                    self._ensure_parent_directories(
                        root,
                        target.parent,
                        created_directories,
                    )
                    self._write_atomically(
                        root,
                        target,
                        change,
                        payloads[change.path],
                    )

            self._update_audit(audit_id, "applied", "")
            self._remove_payload_store(changeset.sandbox_id)
            for change in changeset.changes:
                self._record_trace_activity(
                    changeset.sandbox_id,
                    kind="file",
                    action="filesystem.apply",
                    target=change.path,
                    decision="allowed",
                    reason=f"Applied approved {change.operation} change to the host workspace.",
                    permission_action="filesystem.apply_host",
                    policy_rule="workspace_write.host_apply",
                    approval_id=grant.approval_id,
                    grant_id=grant.grant_id,
                )
            self._record_trace_stage(
                changeset.sandbox_id, "apply", "complete", "Approved workspace changes applied."
            )
            return WorkspaceApplyResult(
                audit_id=audit_id,
                changeset_hash=changeset.changeset_hash,
                workspace_id=changeset.workspace_id,
                applied_changes=changeset.changes,
            )
        except WorkspaceApplyError as exc:
            status = "conflict" if exc.code == "workspace_conflict" else "failed"
            self._update_audit(audit_id, status, exc.code)
            self._record_trace_activity(
                changeset.sandbox_id,
                kind="file",
                action="filesystem.apply",
                target=changeset.changes[0].path,
                decision="denied",
                reason=exc.code,
                permission_action="filesystem.apply_host",
                policy_rule="workspace_write.host_apply",
                approval_id=grant.approval_id,
                grant_id=grant.grant_id,
            )
            self._record_trace_stage(
                changeset.sandbox_id, "apply", "failed", "Approved apply failed safely."
            )
            raise
        except FilesystemWorkspaceError as exc:
            error = WorkspaceApplyError(
                "workspace_unavailable",
                "The selected workspace is unavailable for apply.",
                status_code=409,
            )
            self._update_audit(audit_id, "failed", error.code)
            self._record_trace_activity(
                changeset.sandbox_id,
                kind="file",
                action="filesystem.apply",
                target=changeset.changes[0].path,
                decision="denied",
                reason=error.code,
                permission_action="filesystem.apply_host",
                policy_rule="workspace_write.host_apply",
                approval_id=grant.approval_id,
                grant_id=grant.grant_id,
            )
            self._record_trace_stage(
                changeset.sandbox_id, "apply", "failed", "Approved apply failed safely."
            )
            raise error from exc
        except (OSError, RuntimeError, ValueError) as exc:
            error = WorkspaceApplyError(
                "workspace_apply_failed",
                "Workspace changes could not be applied safely.",
                status_code=409,
            )
            self._update_audit(audit_id, "failed", error.code)
            self._record_trace_activity(
                changeset.sandbox_id,
                kind="file",
                action="filesystem.apply",
                target=changeset.changes[0].path,
                decision="denied",
                reason=error.code,
                permission_action="filesystem.apply_host",
                policy_rule="workspace_write.host_apply",
                approval_id=grant.approval_id,
                grant_id=grant.grant_id,
            )
            self._record_trace_stage(
                changeset.sandbox_id, "apply", "failed", "Approved apply failed safely."
            )
            raise error from exc

    def _record_trace_activity(self, sandbox_id: str, **activity: str) -> None:
        recorder = getattr(self._debug_service, "record_activity", None)
        if callable(recorder):
            try:
                recorder(sandbox_id, **activity)
            except Exception:  # noqa: BLE001 - Trace is non-authoritative.
                return

    def _record_trace_stage(
        self, sandbox_id: str, key: str, status: str, note: str
    ) -> None:
        recorder = getattr(self._debug_service, "record_stage", None)
        if callable(recorder):
            try:
                recorder(sandbox_id, key, status, note)
            except Exception:  # noqa: BLE001 - Trace is non-authoritative.
                return

    def list_audit(self, *, limit: int = 100) -> list[WorkspaceApplyAuditRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("Audit limit must be between 1 and 500.")
        with closing(self._connect_audit()) as connection:
            rows = connection.execute(
                """SELECT audit_id, created_at, workspace_id, changeset_hash,
                          status, change_count, changed_paths, error_code
                   FROM workspace_apply_audit ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            WorkspaceApplyAuditRecord(
                audit_id=str(row["audit_id"]),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                workspace_id=str(row["workspace_id"]),
                changeset_hash=str(row["changeset_hash"]),
                status=str(row["status"]),
                change_count=int(row["change_count"]),
                changed_paths=tuple(json.loads(str(row["changed_paths"]))),
                error_code=str(row["error_code"] or ""),
            )
            for row in rows
        ]

    def _validate_changeset(self, value: WorkspaceChangeSet) -> WorkspaceChangeSet:
        try:
            changeset = WorkspaceChangeSet.model_validate(
                value.model_dump(mode="json")
                if isinstance(value, WorkspaceChangeSet)
                else value
            )
        except (ValidationError, AttributeError, TypeError) as exc:
            raise WorkspaceApplyError(
                "workspace_changeset_invalid",
                "The workspace changeset is invalid.",
                status_code=400,
            ) from exc
        if not _SANDBOX_ID.fullmatch(changeset.sandbox_id):
            raise WorkspaceApplyError(
                "workspace_changeset_invalid",
                "The sandbox changeset identifier is invalid.",
                status_code=400,
            )
        if calculate_changeset_hash(changeset) != changeset.changeset_hash:
            raise WorkspaceApplyError(
                "workspace_changeset_hash_mismatch",
                "The workspace changeset content has changed.",
                status_code=409,
            )
        paths = [change.path for change in changeset.changes]
        if len(paths) != len(set(paths)):
            raise WorkspaceApplyError(
                "workspace_changeset_invalid",
                "The workspace changeset contains duplicate paths.",
                status_code=400,
            )
        if len(changeset.changes) > MAX_WORKSPACE_CHANGED_FILES:
            raise WorkspaceApplyError(
                "workspace_changeset_limit",
                "The workspace changeset contains too many files.",
                status_code=413,
            )
        total_bytes = 0
        for change in changeset.changes:
            if is_protected_workspace_path(change.path):
                raise WorkspaceApplyError(
                    "workspace_path_protected",
                    "The workspace changeset includes a protected path.",
                    status_code=403,
                )
            for mode in (change.mode_before, change.mode_after):
                if mode is not None and mode & 0o7000:
                    raise WorkspaceApplyError(
                        "workspace_mode_unsupported",
                        "Workspace changes cannot set special file permissions.",
                        status_code=403,
                    )
            changed_size = max(change.size_before or 0, change.size_after or 0)
            if changed_size > MAX_WORKSPACE_CHANGED_FILE_BYTES:
                raise WorkspaceApplyError(
                    "workspace_changeset_limit",
                    "A changed workspace file exceeds the size limit.",
                    status_code=413,
                )
            total_bytes += changed_size
        if total_bytes > MAX_WORKSPACE_TOTAL_CHANGED_BYTES:
            raise WorkspaceApplyError(
                "workspace_changeset_limit",
                "Workspace changes exceed the total size limit.",
                status_code=413,
            )
        return changeset

    def _consume_approval(
        self,
        changeset: WorkspaceChangeSet,
        approval_id: str,
    ) -> PermissionGrant:
        scope = {
            "action": "filesystem.apply_host",
            "workspace_id": changeset.workspace_id,
            "target": changeset.changeset_hash,
        }
        try:
            approval = self.approval_service.get(approval_id)
            if approval.requested_scope != scope:
                raise WorkspaceApplyError(
                    "approval_grant_scope_mismatch",
                    "The approval is not bound to this changeset and workspace.",
                    status_code=403,
                )
            grant = self.approval_service.consume_grant(
                approval_id,
                action="filesystem.apply_host",
                scope=scope,
                run_id=approval.run_id,
                tool_call_id=approval.tool_call_id,
            )
        except SandboxApprovalError as exc:
            raise self._approval_error(exc) from exc
        if (
            grant.approval_id != approval_id
            or grant.action != "filesystem.apply_host"
            or grant.scope != scope
        ):
            raise WorkspaceApplyError(
                "approval_grant_scope_mismatch",
                "The approval grant is not valid for this changeset.",
                status_code=403,
            )
        return grant

    def _assert_base_is_current(self, changeset: WorkspaceChangeSet) -> None:
        try:
            snapshot = self.filesystem_workspace_service.snapshot(
                changeset.workspace_id
            )
        except FilesystemWorkspaceError as exc:
            raise WorkspaceApplyError(
                "workspace_unavailable",
                "The selected workspace is unavailable for apply.",
                status_code=409,
            ) from exc
        current = create_workspace_snapshot(
            changeset.workspace_id,
            [
                WorkspaceSnapshotFile(
                    relative_path=str(item["relative_path"]),
                    sha256=str(item["sha256"]),
                    size=int(item["size_bytes"]),
                    mode=int(item.get("mode", 0o644)),
                )
                for item in snapshot.manifest
            ],
        )
        if current.snapshot_hash != changeset.base_snapshot_hash:
            raise WorkspaceApplyError(
                "workspace_conflict",
                "The host workspace changed after this changeset was created.",
                status_code=409,
            )

    def _load_payloads(self, changeset: WorkspaceChangeSet) -> dict[str, bytes]:
        writes = [
            change
            for change in changeset.changes
            if change.operation in {"create", "modify"}
        ]
        if not writes:
            return {}
        if not _SANDBOX_ID.fullmatch(changeset.sandbox_id):
            raise WorkspaceApplyError(
                "workspace_changeset_invalid",
                "The sandbox changeset identifier is invalid.",
                status_code=400,
            )
        sandbox_root = self.change_store_root / changeset.sandbox_id
        try:
            root_stat = sandbox_root.lstat()
            if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
                raise WorkspaceApplyError(
                    "workspace_payload_unavailable",
                    "The retained workspace changes are unavailable.",
                    status_code=404,
                )
        except FileNotFoundError as exc:
            raise WorkspaceApplyError(
                "workspace_payload_unavailable",
                "The retained workspace changes are unavailable.",
                status_code=404,
            ) from exc
        payloads: dict[str, bytes] = {}
        total_bytes = 0
        for change in writes:
            source = sandbox_root.joinpath(*PurePosixPath(change.path).parts)
            self._assert_safe_parent_chain(sandbox_root, source)
            try:
                metadata = source.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise WorkspaceApplyError(
                        "workspace_payload_invalid",
                        "A retained workspace change is not a regular file.",
                        status_code=409,
                    )
                if metadata.st_size != change.size_after:
                    raise WorkspaceApplyError(
                        "workspace_payload_invalid",
                        "A retained workspace change does not match its changeset.",
                        status_code=409,
                    )
                content = self._read_host_file(source, metadata)
            except WorkspaceApplyError:
                raise
            except OSError as exc:
                raise WorkspaceApplyError(
                    "workspace_payload_unavailable",
                    "A retained workspace change could not be read.",
                    status_code=404,
                ) from exc
            if (
                len(content) != change.size_after
                or hashlib.sha256(content).hexdigest() != change.after_sha256
            ):
                raise WorkspaceApplyError(
                    "workspace_payload_invalid",
                    "A retained workspace change does not match its changeset.",
                    status_code=409,
                )
            total_bytes += len(content)
            if total_bytes > MAX_WORKSPACE_TOTAL_CHANGED_BYTES:
                raise WorkspaceApplyError(
                    "workspace_changeset_limit",
                    "Workspace changes exceed the total size limit.",
                    status_code=413,
                )
            payloads[change.path] = content
        return payloads

    def _assert_target_matches_base(
        self,
        root: Path,
        change: WorkspaceChange,
    ) -> None:
        target = self._target_path(root, change.path)
        if change.operation == "create":
            if target.exists() or target.is_symlink():
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A file targeted for creation already exists on the host.",
                    status_code=409,
                )
            return
        try:
            metadata = target.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A changed host path is no longer a regular file.",
                    status_code=409,
                )
            content = self._read_host_file(target, metadata)
        except WorkspaceApplyError:
            raise
        except OSError as exc:
            raise WorkspaceApplyError(
                "workspace_conflict",
                "A file targeted for modification is no longer available.",
                status_code=409,
            ) from exc
        if (
            len(content) != change.size_before
            or hashlib.sha256(content).hexdigest() != change.before_sha256
            or stat.S_IMODE(metadata.st_mode) != change.mode_before
        ):
            raise WorkspaceApplyError(
                "workspace_conflict",
                "A target file changed after this changeset was created.",
                status_code=409,
            )

    def _target_path(self, root: Path, relative_path: str) -> Path:
        candidate = root
        for part in PurePosixPath(relative_path).parts:
            candidate = candidate / part
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A target path could not be inspected safely.",
                    status_code=409,
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A target path contains a symbolic link.",
                    status_code=409,
                )
            if (
                candidate != root
                and candidate != root / PurePosixPath(relative_path)
                and not stat.S_ISDIR(metadata.st_mode)
            ):
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A parent path is not a directory.",
                    status_code=409,
                )
            if candidate.resolve(strict=True) != candidate:
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A target path resolves outside the selected workspace.",
                    status_code=409,
                )
        try:
            candidate.absolute().relative_to(root.absolute())
        except ValueError as exc:
            raise WorkspaceApplyError(
                "workspace_path_invalid",
                "A workspace path is outside the selected folder.",
                status_code=400,
            ) from exc
        return candidate

    @staticmethod
    def _assert_safe_parent_chain(root: Path, target: Path) -> None:
        current = root
        try:
            for part in target.relative_to(root).parts[:-1]:
                current = current / part
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise WorkspaceApplyError(
                        "workspace_payload_invalid",
                        "A retained change path contains an unsafe directory.",
                        status_code=409,
                    )
            target.absolute().relative_to(root.absolute())
        except WorkspaceApplyError:
            raise
        except (OSError, ValueError) as exc:
            raise WorkspaceApplyError(
                "workspace_payload_invalid",
                "A retained change path is invalid.",
                status_code=409,
            ) from exc

    @staticmethod
    def _read_host_file(path: Path, initial_stat: os.stat_result) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_dev != initial_stat.st_dev
                or opened_stat.st_ino != initial_stat.st_ino
            ):
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A target file changed while it was being checked.",
                    status_code=409,
                )
            chunks: list[bytes] = []
            size = 0
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                while chunk := handle.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_WORKSPACE_CHANGED_FILE_BYTES:
                        raise WorkspaceApplyError(
                            "workspace_changeset_limit",
                            "A changed workspace file exceeds the size limit.",
                            status_code=413,
                        )
                    chunks.append(chunk)
            final_stat = path.lstat()
            if (
                stat.S_ISLNK(final_stat.st_mode)
                or final_stat.st_size != size
                or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
                or stat.S_IMODE(final_stat.st_mode) != stat.S_IMODE(opened_stat.st_mode)
            ):
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A target file changed while it was being checked.",
                    status_code=409,
                )
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _ensure_parent_directories(
        self,
        root: Path,
        parent: Path,
        created_directories: list[Path],
    ) -> None:
        relative = parent.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            self._target_path(root, current.relative_to(root).as_posix())
            if not current.exists():
                current.mkdir(mode=0o755)
                created_directories.append(current)
            elif not current.is_dir() or current.is_symlink():
                raise WorkspaceApplyError(
                    "workspace_conflict",
                    "A parent path is not a safe directory.",
                    status_code=409,
                )

    def _write_atomically(
        self,
        root: Path,
        target: Path,
        change: WorkspaceChange,
        content: bytes,
    ) -> None:
        mode = change.mode_before if change.operation == "modify" else change.mode_after
        if mode is None:
            raise WorkspaceApplyError(
                "workspace_changeset_invalid",
                "The workspace change does not include a file mode.",
                status_code=400,
            )
        temporary = target.with_name(f".aitrans-{uuid4().hex}.partial")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.close(descriptor)
            descriptor = -1
            os.chmod(temporary, mode & 0o777)
            self._assert_target_matches_base(root, change)
            if change.operation == "create":
                os.link(temporary, target)
                temporary.unlink()
            else:
                os.replace(temporary, target)
            self._fsync_directory(target.parent)
        except FileExistsError as exc:
            raise WorkspaceApplyError(
                "workspace_conflict",
                "A file targeted for creation already exists on the host.",
                status_code=409,
            ) from exc
        except WorkspaceApplyError:
            raise
        except OSError as exc:
            raise WorkspaceApplyError(
                "workspace_apply_failed",
                "An atomic workspace file write failed.",
                status_code=409,
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _remove_payload_store(self, sandbox_id: str) -> None:
        if not _SANDBOX_ID.fullmatch(sandbox_id):
            return
        root = self.change_store_root / sandbox_id
        try:
            metadata = root.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            return
        shutil.rmtree(root, ignore_errors=True)

    def _initialize_audit_store(self) -> None:
        self.audit_database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(
            sqlite3.connect(self.audit_database_path, timeout=5.0)
        ) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS workspace_apply_audit (
                    audit_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    changeset_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    change_count INTEGER NOT NULL,
                    changed_paths TEXT NOT NULL,
                    error_code TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_workspace_apply_audit_created_at "
                "ON workspace_apply_audit(created_at DESC)"
            )
            connection.commit()
        if os.name != "nt":
            self.audit_database_path.chmod(0o600)

    def _connect_audit(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.audit_database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _record_audit(self, changeset: WorkspaceChangeSet, status: str) -> str:
        audit_id = f"wa_{uuid4().hex}"
        created_at = datetime.now(UTC).isoformat()
        paths = json.dumps(
            [change.path for change in changeset.changes],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._lock, closing(self._connect_audit()) as connection:
            connection.execute(
                """INSERT INTO workspace_apply_audit
                   (audit_id, created_at, workspace_id, changeset_hash, status,
                    change_count, changed_paths, error_code)
                   VALUES (?, ?, ?, ?, ?, ?, ?, '')""",
                (
                    audit_id,
                    created_at,
                    changeset.workspace_id,
                    changeset.changeset_hash,
                    status,
                    len(changeset.changes),
                    paths,
                ),
            )
            connection.execute(
                """DELETE FROM workspace_apply_audit WHERE audit_id IN (
                       SELECT audit_id FROM workspace_apply_audit
                       ORDER BY created_at DESC LIMIT -1 OFFSET ?
                   )""",
                (_MAX_AUDIT_ROWS,),
            )
            connection.commit()
        return audit_id

    def _update_audit(self, audit_id: str, status: str, error_code: str) -> None:
        with self._lock, closing(self._connect_audit()) as connection:
            connection.execute(
                "UPDATE workspace_apply_audit SET status = ?, error_code = ? "
                "WHERE audit_id = ?",
                (status, error_code, audit_id),
            )
            connection.commit()

    @staticmethod
    def _approval_error(error: SandboxApprovalError) -> WorkspaceApplyError:
        return WorkspaceApplyError(
            error.code,
            str(error),
            status_code=error.status_code,
        )


__all__ = [
    "WorkspaceApplyAuditRecord",
    "WorkspaceApplyError",
    "WorkspaceApplyResult",
    "WorkspaceApplyService",
]
