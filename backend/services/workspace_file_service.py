"""Scoped text file operations with durable receipts and conflict-aware undo.

This service owns filesystem effects. Models receive relative paths only; a
trusted session supplies the workspace and write access. File contents are data.
"""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.infrastructure.paths import data_root
from backend.sandbox.workspace_snapshot import is_protected_workspace_path

MAX_TEXT_BYTES = 2 * 1024 * 1024
FILE_READ_TOOLS = {"list_workspace_files", "search_workspace_text", "read_workspace_text"}
FILE_WRITE_TOOLS = {"create_workspace_file", "edit_workspace_file", "write_workspace_file",
                    "create_workspace_directory", "undo_workspace_change"}
FILE_TOOLS = FILE_READ_TOOLS | FILE_WRITE_TOOLS


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def preview_fingerprint(preview):
    """Bind approval to the exact effect, including resolved tool defaults."""
    keys = ("relative_path", "operation", "size_before", "size_after", "before_sha256", "after_sha256", "change_id")
    return digest(json.dumps({key: preview.get(key, "") for key in keys}, sort_keys=True).encode())


class WorkspaceFileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class WorkspaceFileService:
    def __init__(self, workspaces, database_path: Path | None = None):
        self.workspaces = workspaces
        self.database_path = database_path or data_root() / "runtime" / "workspace_file_changes.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS file_changes (
                change_id TEXT PRIMARY KEY, operation_key TEXT UNIQUE, fingerprint TEXT NOT NULL,
                workspace_id TEXT NOT NULL, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
                relative_path TEXT NOT NULL, operation TEXT NOT NULL, before_content BLOB,
                after_sha256 TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                receipt TEXT NOT NULL DEFAULT '{}', undone_by TEXT NOT NULL DEFAULT '')""")
            db.execute("""CREATE TABLE IF NOT EXISTS file_undo_approvals (
                token TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, session_id TEXT NOT NULL,
                change_id TEXT NOT NULL, preview_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0)""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _write_lock(self):
        # Serialize backend processes and independently constructed services.
        # External editors are detected by the version check before publishing.
        with self.database_path.with_suffix(".lock").open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _plain(metadata):
        return not (stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & 0x400)

    @staticmethod
    def _directory_identity(target):
        metadata = target.stat()
        return digest(json.dumps([metadata.st_dev, metadata.st_ino,
                                  getattr(metadata, "st_birthtime_ns", metadata.st_ctime_ns if os.name == "nt" else 0)]).encode())

    def path(self, workspace_id: str, relative_path: str, *, allow_root=False) -> Path:
        root = self.workspaces.active_root_path(workspace_id)
        raw = relative_path.replace("\\", "/")
        if allow_root and raw in {"", "."}:
            return root
        parts = raw.split("/")
        if (not raw or len(raw) > 1024 or any(part in {"", ".", ".."} for part in parts)
                or any(re.search(r'[\x00-\x1f<>:"|?*]', part) or part.endswith((" ", "."))
                       or re.match(r"^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", part, re.I)
                       for part in parts)
                or is_protected_workspace_path(raw)):
            raise WorkspaceFileError("invalid_path", "请使用工作区内有效的相对路径；该路径不可访问。")
        target = root.joinpath(*parts)
        current = root
        for part in parts:
            current = current / part
            if current.exists() or current.is_symlink():
                metadata = current.lstat()
                if not self._plain(metadata) or (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1):
                    raise WorkspaceFileError("linked_path", "不能通过链接访问或修改文件。")
        if not target.resolve().is_relative_to(root):
            raise WorkspaceFileError("outside_workspace", "目标不在当前工作区内。")
        # Internal state is never available as user file content, even when the
        # application repository or its runtime folder was selected as a root.
        for database in (self.database_path, self.workspaces.database_path):
            resolved_database = database.resolve()
            resolved_target = target.resolve()
            if (resolved_target == resolved_database or (resolved_target.parent == resolved_database.parent and resolved_target.name.startswith(resolved_database.name))
                    or resolved_target.is_relative_to((data_root() / "runtime").resolve())):
                raise WorkspaceFileError("protected_path", "不能访问应用内部运行数据。")
        return target

    def _bytes(self, workspace_id, relative_path):
        target = self.path(workspace_id, relative_path)
        if not target.is_file():
            raise WorkspaceFileError("file_missing", "目标文件不存在。")
        if target.stat().st_size > MAX_TEXT_BYTES:
            raise WorkspaceFileError("file_too_large", "文本文件超过 2 MB，请缩小处理范围。")
        content = target.read_bytes()
        if len(content) > MAX_TEXT_BYTES or b"\x00" in content:
            raise WorkspaceFileError("unsupported_text", "此文件不是支持的文本文件。")
        self.path(workspace_id, relative_path)
        return content

    @staticmethod
    def _decode(content):
        try:
            return content.decode("utf-8-sig"), "utf-8-sig" if content.startswith(b"\xef\xbb\xbf") else "utf-8"
        except UnicodeDecodeError as exc:
            raise WorkspaceFileError("unsupported_encoding", "当前精确编辑支持 UTF-8 文本；原文件未修改。") from exc

    def read(self, workspace_id, relative_path, start_line=1, max_lines=200):
        content = self._bytes(workspace_id, relative_path)
        text, encoding = self._decode(content)
        lines = text.splitlines(keepends=True)
        selected = lines[start_line - 1:start_line - 1 + max_lines]
        return {"relative_path": relative_path.replace("\\", "/"), "text": "".join(selected),
                "sha256": digest(content), "size_bytes": len(content), "encoding": encoding,
                "start_line": start_line, "next_line": start_line + len(selected),
                "total_lines": len(lines), "has_more": start_line - 1 + len(selected) < len(lines)}

    def list(self, workspace_id, directory="", pattern="*", offset=0, limit=100):
        root = self.workspaces.active_root_path(workspace_id)
        folder = self.path(workspace_id, directory, allow_root=True)
        if not folder.is_dir():
            raise WorkspaceFileError("directory_missing", "目标文件夹不存在。")
        entries = []
        # Nonrecursive browsing is paged; callers explicitly descend directories.
        for item in folder.iterdir():
            relative = item.relative_to(root).as_posix()
            try:
                self.path(workspace_id, relative)
                metadata = item.stat()
            except (ValueError, OSError):
                continue
            if fnmatch.fnmatchcase(item.name.casefold(), pattern.casefold()):
                entries.append({"relative_path": relative, "name": item.name,
                                "kind": "directory" if item.is_dir() else "file",
                                "size_bytes": metadata.st_size if item.is_file() else 0})
        entries.sort(key=lambda entry: (entry["kind"] != "directory", entry["name"].casefold()))
        return {"directory": directory, "entries": entries[offset:offset + limit], "total": len(entries),
                "next_offset": offset + len(entries[offset:offset + limit]), "has_more": offset + limit < len(entries)}

    def search(self, workspace_id, query, directory="", pattern="*", offset=0, limit=100):
        root = self.workspaces.active_root_path(workspace_id)
        folder = self.path(workspace_id, directory, allow_root=True)
        if not folder.is_dir():
            raise WorkspaceFileError("directory_missing", "目标文件夹不存在。")
        matches, visited, truncated = [], 0, False
        for current, directories, files in os.walk(folder, followlinks=False):
            safe = []
            for name in sorted(directories):
                if name in {"node_modules", ".venv", "__pycache__"}:
                    continue
                try:
                    self.path(workspace_id, (Path(current) / name).relative_to(root).as_posix())
                    safe.append(name)
                except (ValueError, OSError):
                    continue
            directories[:] = safe
            for name in sorted(files):
                visited += 1
                if visited > 4096:
                    truncated = True
                    break
                if not fnmatch.fnmatchcase(name.casefold(), pattern.casefold()):
                    continue
                relative = (Path(current) / name).relative_to(root).as_posix()
                try:
                    text, _ = self._decode(self._bytes(workspace_id, relative))
                except (ValueError, OSError):
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        matches.append({"relative_path": relative, "line": number, "text": line[:1000]})
                        if len(matches) >= offset + limit + 1:
                            truncated = True
                            break
                if truncated:
                    break
            if truncated:
                break
        return {"matches": matches[offset:offset + limit], "next_offset": offset + len(matches[offset:offset + limit]),
                "has_more": len(matches) > offset + limit, "scan_truncated": truncated, "scanned_files": min(visited, 4096)}

    def _prepare(self, workspace_id, operation, arguments):
        relative = arguments.get("relative_path", "")
        original_change = None
        if operation == "undo":
            with self._db() as db:
                original_change = db.execute("SELECT * FROM file_changes WHERE change_id=? AND workspace_id=?",
                                             (arguments["change_id"], workspace_id)).fetchone()
            if not original_change or original_change["status"] != "applied" or original_change["undone_by"]:
                raise WorkspaceFileError("change_unavailable", "该变更不存在、已撤销或结果尚未确认。")
            if original_change["operation"] == "undo":
                raise WorkspaceFileError("change_unavailable", "不能重复撤销恢复记录。")
            relative = original_change["relative_path"]
        target = self.path(workspace_id, relative)
        if not target.parent.is_dir():
            raise WorkspaceFileError("parent_missing", "父文件夹不存在，请先明确创建该目录。")
        if operation in {"create", "mkdir"}:
            if target.exists():
                raise WorkspaceFileError("file_exists", "同名文件或文件夹已存在，未覆盖；请指定其他名称或明确修改。")
            before = None
            after = arguments.get("content", "").encode("utf-8") if operation == "create" else None
        elif original_change and original_change["operation"] == "mkdir":
            if (not target.is_dir() or any(target.iterdir())
                    or self._directory_identity(target) != original_change["after_sha256"]):
                raise WorkspaceFileError("file_conflict", "文件夹已变化或非空，不能撤销创建。")
            before, after = None, None
        else:
            before = self._bytes(workspace_id, relative)
            expected = original_change["after_sha256"] if original_change else arguments["expected_sha256"]
            if digest(before) != expected:
                raise WorkspaceFileError("file_conflict", "文件已发生变化，请重新读取并确认差异；原文件未修改。")
            if original_change:
                after = original_change["before_content"]
            else:
                text, encoding = self._decode(before)
                if operation == "edit":
                    if text.count(arguments["old_text"]) != 1:
                        raise WorkspaceFileError("ambiguous_edit", "待替换片段不存在或不唯一，请提供更完整的片段。")
                    text = text.replace(arguments["old_text"], arguments["new_text"], 1)
                else:
                    text = arguments["content"]
                after = text.encode(encoding)
        if after is not None and (len(after) > MAX_TEXT_BYTES or b"\x00" in after):
            raise WorkspaceFileError("unsupported_text", "写入内容必须是 2 MB 以内的文本。")
        return relative, target, before, after, original_change

    def preview(self, workspace_id, operation, arguments):
        relative, _, before, after, original = self._prepare(workspace_id, operation, arguments)
        before_text = self._decode(before)[0] if before is not None else ""
        after_text = self._decode(after)[0] if after is not None else ""
        diff_lines = difflib.unified_diff(before_text.splitlines(keepends=True), after_text.splitlines(keepends=True),
                                         fromfile=relative, tofile=relative)
        difference = "".join(line if line.endswith(("\n", "\r")) else line + "\n\\ No newline at end of file\n"
                             for line in diff_lines)
        return {"relative_path": relative, "operation": operation,
                "size_before": len(before) if before is not None else 0,
                "size_after": len(after) if after is not None else 0,
                "before_sha256": digest(before) if before is not None else original["after_sha256"] if original and original["operation"] == "mkdir" else "",
                "after_sha256": digest(after) if after is not None else "",
                "diff": difference[:20000], "diff_truncated": len(difference) > 20000,
                "change_id": original["change_id"] if original else ""}

    def apply(self, workspace_id, operation, arguments, *, operation_key="", session_id="", run_id=""):
        with self._lock, self._write_lock():
            fingerprint = digest(json.dumps([workspace_id, operation, arguments], ensure_ascii=False, sort_keys=True).encode())
            key = operation_key or uuid4().hex
            with self._db() as db:
                saved = db.execute("SELECT * FROM file_changes WHERE operation_key=?", (key,)).fetchone()
            if saved:
                if saved["fingerprint"] != fingerprint or saved["status"] != "applied":
                    raise WorkspaceFileError("write_unresolved", "该写入已有未确认的执行记录，不能自动重放。")
                receipt = json.loads(saved["receipt"])
                self.verify(workspace_id, receipt)
                return receipt
            relative, target, before, after, original = self._prepare(workspace_id, operation, arguments)
            change_id = uuid4().hex
            after_hash = digest(after) if after is not None else ""
            created_at = datetime.now(UTC).isoformat()
            with self._db() as db:
                db.execute("INSERT INTO file_changes (change_id,operation_key,fingerprint,workspace_id,session_id,run_id,relative_path,operation,before_content,after_sha256,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (change_id, key, fingerprint, workspace_id, session_id, run_id, relative, operation, before, after_hash, "pending", created_at))
            temporary = None
            try:
                if operation == "mkdir":
                    self.path(workspace_id, relative).mkdir()
                    after_hash = self._directory_identity(target)
                elif original and original["operation"] == "mkdir":
                    self.path(workspace_id, relative).rmdir()
                elif after is None:
                    self._prepare(workspace_id, operation, arguments)
                    target.unlink()
                else:
                    fd, name = tempfile.mkstemp(prefix=".aitrans-write-", dir=target.parent)
                    temporary = Path(name)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(after)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if before is not None:
                        os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
                    # Recheck immediately before publishing the completed file.
                    self._prepare(workspace_id, operation, arguments)
                    if operation == "create":
                        os.link(temporary, target)  # Exclusive publication, never overwrites.
                        temporary.unlink()
                    else:
                        os.replace(temporary, target)
                    temporary = None
                absent = operation == "undo" and after is None
                receipt = {"change_id": change_id, "workspace_id": workspace_id, "relative_path": relative,
                           "operation": operation, "kind": "directory" if operation == "mkdir" or (original and original["operation"] == "mkdir") else "file",
                           "sha256": after_hash, "size_bytes": len(after) if after is not None else 0,
                           "exists": not absent, "created_at": created_at, "run_id": run_id}
                self.verify(workspace_id, receipt)
                with self._db() as db:
                    db.execute("UPDATE file_changes SET status='applied', receipt=?, after_sha256=? WHERE change_id=?", (json.dumps(receipt), after_hash, change_id))
                    if original:
                        db.execute("UPDATE file_changes SET undone_by=? WHERE change_id=?", (change_id, original["change_id"]))
                return receipt
            except Exception:
                # Keep the pending journal on uncertain effects; never replay them.
                raise
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def verify(self, workspace_id, receipt):
        target = self.path(workspace_id, receipt["relative_path"])
        if not receipt["exists"]:
            valid = not target.exists()
        elif receipt["kind"] == "directory":
            valid = target.is_dir() and self._directory_identity(target) == receipt["sha256"]
        else:
            actual = self._bytes(workspace_id, receipt["relative_path"])
            valid = digest(actual) == receipt["sha256"] and len(actual) == receipt["size_bytes"]
        if not valid:
            raise WorkspaceFileError("readback_failed", "文件操作结果已变化或无法核对，不能确认成功。")
        return True

    def changes(self, workspace_id, session_id, limit=20):
        with self._db() as db:
            rows = db.execute("SELECT receipt,undone_by FROM file_changes WHERE workspace_id=? AND session_id=? AND status='applied' ORDER BY created_at DESC LIMIT ?",
                              (workspace_id, session_id, limit)).fetchall()
        return [{**json.loads(row["receipt"]), "undone_by": row["undone_by"]} for row in rows]

    def undo_preview(self, workspace_id, session_id, change_id):
        import time
        with self._db() as db:
            owned = db.execute("SELECT 1 FROM file_changes WHERE change_id=? AND workspace_id=? AND session_id=?",
                               (change_id, workspace_id, session_id)).fetchone()
        if not owned:
            raise WorkspaceFileError("change_unavailable", "此会话中没有对应变更。")
        preview = self.preview(workspace_id, "undo", {"change_id": change_id})
        token = uuid4().hex
        preview_hash = digest(json.dumps(preview, sort_keys=True).encode())
        with self._db() as db:
            db.execute("INSERT INTO file_undo_approvals VALUES (?,?,?,?,?,?,0)",
                       (token, workspace_id, session_id, change_id, preview_hash, time.time() + 300))
        return {**preview, "approval_token": token}

    def undo_confirmed(self, workspace_id, session_id, token):
        import time
        with self._lock, self._db() as db:
            row = db.execute("SELECT * FROM file_undo_approvals WHERE token=? AND workspace_id=? AND session_id=? AND consumed=0 AND expires_at>?",
                             (token, workspace_id, session_id, time.time())).fetchone()
            if not row:
                raise WorkspaceFileError("approval_invalid", "撤销确认已失效，请重新查看差异。")
            preview = self.preview(workspace_id, "undo", {"change_id": row["change_id"]})
            if digest(json.dumps(preview, sort_keys=True).encode()) != row["preview_hash"]:
                raise WorkspaceFileError("file_conflict", "文件已变化，请重新查看差异。")
            if db.execute("UPDATE file_undo_approvals SET consumed=1 WHERE token=? AND consumed=0", (token,)).rowcount != 1:
                raise WorkspaceFileError("approval_invalid", "撤销确认已使用。")
            db.commit()
            return self.apply(workspace_id, "undo", {"change_id": row["change_id"]},
                              operation_key=f"undo:{token}", session_id=session_id)
