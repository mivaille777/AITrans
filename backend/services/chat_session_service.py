"""Durable Chat controls and conversation-local imports (no Knowledge indexing)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.infrastructure.paths import data_root
from backend.rag.parsers import get_parser_for_path
from backend.sandbox.workspace_snapshot import is_protected_workspace_path
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService


class ChatAttachment(BaseModel):
    attachment_id: str
    name: str
    relative_path: str
    size_bytes: int
    text_chars: int


class ChatSessionConfiguration(BaseModel):
    session_id: str
    filesystem_workspace_id: str = ""
    execution_mode: Literal["react", "plan_execute"] = "react"
    filesystem_access: Literal["read_only", "read_write"] = "read_write"
    attachments: list[ChatAttachment] = Field(default_factory=list)
    pending_run_id: str = ""


class ChatSessionService:
    def __init__(
        self, workspaces: FilesystemWorkspaceService, database_path: Path | None = None
    ):
        self.workspaces = workspaces
        self.database_path = (
            database_path or data_root() / "runtime" / "chat_sessions.sqlite3"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with sqlite3.connect(self.database_path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY, configuration TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_imports (attachment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL, metadata TEXT NOT NULL, text TEXT NOT NULL)"
            )

    def get(self, session_id: str) -> ChatSessionConfiguration:
        with sqlite3.connect(self.database_path) as db:
            row = db.execute(
                "SELECT configuration FROM chat_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return (
            ChatSessionConfiguration.model_validate_json(row[0])
            if row
            else ChatSessionConfiguration(session_id=session_id)
        )

    def _save(self, config: ChatSessionConfiguration) -> ChatSessionConfiguration:
        with sqlite3.connect(self.database_path) as db:
            db.execute(
                "INSERT INTO chat_sessions VALUES (?,?) ON CONFLICT(session_id) DO UPDATE SET configuration=excluded.configuration",
                (config.session_id, config.model_dump_json()),
            )
        return config

    def update(
        self,
        session_id: str,
        *,
        filesystem_workspace_id: str | None = None,
        execution_mode: str | None = None,
        filesystem_access: str | None = None,
    ) -> ChatSessionConfiguration:
        with self._lock:
            config = self.get(session_id)
            if filesystem_access is not None:
                if filesystem_access not in {"read_only", "read_write"}:
                    raise ValueError("未知文件访问权限。")
                if config.pending_run_id and filesystem_access != config.filesystem_access:
                    raise ValueError("请先执行或取消当前计划，再切换权限。")
                config.filesystem_access = filesystem_access
            if (
                filesystem_workspace_id is not None
                and filesystem_workspace_id != config.filesystem_workspace_id
            ):
                if filesystem_workspace_id:
                    self.workspaces.active_root_path(filesystem_workspace_id)
                if config.pending_run_id:
                    raise ValueError("请先执行或取消当前计划，再切换工作区。")
                config.filesystem_workspace_id = filesystem_workspace_id
                config.attachments = []
            if execution_mode is not None:
                if execution_mode not in {"react", "plan_execute"}:
                    raise ValueError("未知执行模式。")
                if config.pending_run_id and execution_mode != config.execution_mode:
                    raise ValueError("请先执行或取消当前计划，再切换模式。")
                config.execution_mode = execution_mode
            return self._save(config)

    def import_file(
        self, session_id: str, source_path: str
    ) -> ChatSessionConfiguration:
        with self._lock:
            config = self.get(session_id)
            if not config.filesystem_workspace_id:
                raise ValueError("请先选择工作区，再导入文件。")
            if config.filesystem_access == "read_only":
                raise ValueError("当前工作区为只读，不能导入文件副本。")
            if config.pending_run_id:
                raise ValueError("请先执行或取消当前计划，再导入文件。")
            if len(config.attachments) >= 16:
                raise ValueError("每个会话最多导入 16 个文件。")
            source = Path(source_path)
            if not source.is_absolute() or source.is_symlink() or not source.is_file():
                raise ValueError("请选择有效的本地文件。")
            if source.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("单个文件不能超过 16 MB。")
            # Use the existing PDF/DOCX/text parsers without indexing globally.
            parser = get_parser_for_path(source)
            root = self.workspaces.active_root_path(config.filesystem_workspace_id)
            folder = root / "AITrans Chat Imports"
            folder.mkdir(exist_ok=True)
            if folder.is_symlink() or folder.resolve().parent != root.resolve():
                raise ValueError("工作区导入目录不可用。")
            attachment_id = uuid4().hex
            target = folder / f"{attachment_id[:12]}-{source.name}"
            try:
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                text = parser.parse(target).text
                if not text.strip():
                    raise ValueError("文件中没有可读取的文字；请提供带文字层的文档。")
                if len(text) > 2_000_000:
                    raise ValueError("文件文字内容过大，请拆分后导入。")
                attachment = ChatAttachment(
                    attachment_id=attachment_id,
                    name=source.name,
                    relative_path=target.relative_to(root).as_posix(),
                    size_bytes=target.stat().st_size,
                    text_chars=len(text),
                )
                with sqlite3.connect(self.database_path) as db:
                    db.execute(
                        "INSERT INTO chat_imports VALUES (?,?,?,?,?)",
                        (
                            attachment_id,
                            session_id,
                            config.filesystem_workspace_id,
                            attachment.model_dump_json(),
                            text,
                        ),
                    )
                config.attachments.append(attachment)
                return self._save(config)
            except Exception:
                target.unlink(missing_ok=True)
                raise

    def detach(self, session_id: str, attachment_id: str) -> ChatSessionConfiguration:
        with self._lock:
            config = self.get(session_id)
            if config.pending_run_id:
                raise ValueError("请先执行或取消当前计划，再移除文件。")
            config.attachments = [
                item
                for item in config.attachments
                if item.attachment_id != attachment_id
            ]
            # Detaching never deletes the user's imported workspace copy.
            return self._save(config)

    def set_pending_run(self, session_id: str, run_id: str) -> None:
        with self._lock:
            config = self.get(session_id)
            config.pending_run_id = run_id
            self._save(config)

    def context(self, session_id: str) -> tuple[ChatSessionConfiguration, str]:
        config = self.get(session_id)
        if config.filesystem_workspace_id:
            self.workspaces.active_root_path(config.filesystem_workspace_id)
        fragments = []
        with sqlite3.connect(self.database_path) as db:
            for attachment in config.attachments:
                row = db.execute(
                    "SELECT text FROM chat_imports WHERE attachment_id=? AND session_id=? AND workspace_id=?",
                    (
                        attachment.attachment_id,
                        session_id,
                        config.filesystem_workspace_id,
                    ),
                ).fetchone()
                if row:
                    fragments.append(
                        f"文件：{attachment.name}\n工作区路径：{attachment.relative_path}\n"
                        + row[0][:8_000]
                        + (
                            "\n[仅附带前 8000 字，可调用 read_workspace_file 按位置继续读取。]"
                            if len(row[0]) > 8_000
                            else ""
                        )
                    )
        return config, "\n\n".join(fragments)[:48_000]

    def list_files(self, workspace_id: str) -> list[dict]:
        """Bounded metadata inventory; sandbox byte quotas apply only to execution."""
        root = self.workspaces.active_root_path(workspace_id).resolve()
        files, pending, inspected = [], [root], 0
        while pending and len(files) < 128 and inspected < 4096:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    inspected += 1
                    if inspected > 4096 or len(files) >= 128:
                        break
                    path = Path(entry.path)
                    if path.is_symlink():
                        continue
                    resolved = path.resolve()
                    if not resolved.is_relative_to(root):
                        continue
                    relative = resolved.relative_to(root).as_posix()
                    if is_protected_workspace_path(relative):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(resolved)
                    elif entry.is_file(follow_symlinks=False):
                        files.append(
                            {
                                "relative_path": relative,
                                "size_bytes": entry.stat(follow_symlinks=False).st_size,
                            }
                        )
        return files

    def read_file(
        self, workspace_id: str, relative_path: str, offset: int, limit: int
    ) -> dict:
        root = self.workspaces.active_root_path(workspace_id).resolve()
        path = root / relative_path
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or is_protected_workspace_path(relative_path)
            or not path.is_file()
        ):
            raise ValueError("文件必须位于当前工作区内。")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("读取文件不能超过 16 MB。")
        text = get_parser_for_path(path).parse(path).text
        end = min(len(text), offset + limit)
        return {
            "relative_path": relative_path,
            "text": text[offset:end],
            "offset": offset,
            "next_offset": end,
            "total_chars": len(text),
            "has_more": end < len(text),
        }


def plan_fingerprint(plan: dict) -> str:
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
