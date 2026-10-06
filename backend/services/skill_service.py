"""Bounded local file storage with atomic writes and optimistic concurrency."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

import yaml

from backend.models.skills import (
    SkillDescriptor,
    SkillDetail,
    SkillFile,
    SkillFileContent,
    SkillLibrary,
)

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SKILL_BYTES = 20 * 1024 * 1024
MAX_FILES = 200
MAX_METADATA_BYTES = 64 * 1024
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_DEVICES = re.compile(
    r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", re.IGNORECASE
)


class SkillError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def validate_name(name: str) -> None:
    if (
        len(name) > 64
        or not NAME_PATTERN.fullmatch(name)
        or WINDOWS_DEVICES.fullmatch(name)
    ):
        raise SkillError(
            "名称须为 1–64 个小写字母、数字或单连字符，且不能使用系统保留名称。"
        )


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _relative_path(value: str) -> Path:
    # Reject Windows ADS, absolute paths, traversal and ambiguous trailing dots/spaces
    # on every platform, so imports remain portable.
    parts = value.replace("\\", "/").split("/")
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
        or WINDOWS_DEVICES.fullmatch(part)
        or part.startswith(".")
        for part in parts
    ):
        raise SkillError(
            "文件路径必须是技能目录内的相对路径，不能含隐藏目录或系统保留字符。"
        )
    return Path(*parts)


def _validate_metadata(value: object) -> None:
    """Bound expanded YAML aliases before JSON response serialization."""
    nodes = 0
    text_bytes = 0

    def visit(item: object, depth: int = 0) -> None:
        nonlocal nodes, text_bytes
        nodes += 1
        if nodes > 2048 or depth > 12:
            raise ValueError("Metadata is too complex")
        if isinstance(item, str):
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > MAX_METADATA_BYTES:
                raise ValueError("Expanded metadata is too large")
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError("Metadata keys must be strings")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Non-finite metadata number")
        elif item is not None and not isinstance(item, (int, bool)):
            raise ValueError("Metadata must be JSON-compatible")

    visit(value)


def parse_manifest(content: str, directory_name: str) -> tuple[dict, list[str]]:
    lines = content.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["SKILL.md 缺少 YAML frontmatter（以 --- 开始和结束）。"]
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, ["YAML frontmatter 未闭合。"]
    frontmatter = "\n".join(lines[1:end])
    if len(frontmatter.encode("utf-8")) > MAX_METADATA_BYTES:
        return {}, ["YAML frontmatter 超过 64 KB，请将长内容移入正文或参考文件。"]
    try:
        metadata = yaml.safe_load(frontmatter)
        _validate_metadata(metadata)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        return {}, ["YAML frontmatter 无效或过于复杂；请使用可序列化的字符串键值字段。"]
    if not isinstance(metadata, dict) or not all(
        isinstance(key, str) for key in metadata
    ):
        return {}, ["YAML frontmatter 必须是字符串键的映射。"]
    diagnostics = []
    name = metadata.get("name")
    if not isinstance(name, str):
        diagnostics.append("name 必须是字符串。")
    else:
        try:
            validate_name(name)
        except SkillError as exc:
            diagnostics.append(str(exc))
        if name != directory_name:
            diagnostics.append(f"name 必须与技能目录名 {directory_name} 一致。")
    description = metadata.get("description")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
        diagnostics.append("description 必须是 1–1024 字符的非空字符串。")
    for key, limit in (
        ("license", None),
        ("compatibility", 500),
        ("allowed-tools", None),
    ):
        if key in metadata and (
            not isinstance(metadata[key], str)
            or (limit and not 1 <= len(metadata[key]) <= limit)
        ):
            diagnostics.append(
                f"{key} 必须是字符串" + (f"，长度为 1–{limit}。" if limit else "。")
            )
    if "metadata" in metadata and (
        not isinstance(metadata["metadata"], dict)
        or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in metadata["metadata"].items()
        )
    ):
        diagnostics.append("metadata 必须是字符串键与字符串值的映射。")
    return metadata, diagnostics


class SkillService:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._headers: dict[str, tuple[tuple, dict, list[str]]] = {}

    def descriptors(self) -> list[SkillDescriptor]:
        """Runtime discovery reads frontmatter only, never bodies or resource files."""
        from backend.services.skill_runtime import DOMAINS, infer_category

        with self._lock:
            enabled = self._state()
            result = []
            present = set()
            for name in sorted(enabled):
                if not enabled[name]:
                    continue
                try:
                    directory = self._directory(name)
                    path = self._file(directory, "SKILL.md")
                    info = path.stat()
                    if not path.is_file() or info.st_size > MAX_FILE_BYTES:
                        continue
                    stamp = (
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                        info.st_size,
                        info.st_ino,
                    )
                    present.add(name)
                    cached = self._headers.get(name)
                    if cached is None or cached[0] != stamp:
                        # Unbuffered reads stop exactly at the closing delimiter.
                        with path.open("rb", buffering=0) as stream:
                            lines, size = [], 0
                            while size <= MAX_METADATA_BYTES + 16:
                                line = stream.readline(MAX_METADATA_BYTES + 17 - size)
                                if not line:
                                    break
                                size += len(line)
                                lines.append(line)
                                if len(lines) > 1 and line.strip() == b"---":
                                    break
                                if (
                                    len(lines) == 1
                                    and line.lstrip(b"\xef\xbb\xbf").strip() != b"---"
                                ):
                                    break
                        metadata, issues = parse_manifest(
                            b"".join(lines).decode("utf-8-sig"), name
                        )
                        cached = (stamp, metadata, issues)
                        self._headers[name] = cached
                    _, metadata, issues = cached
                    if issues:
                        continue
                    extra = metadata.get("metadata", {})
                    category = extra.get("aitrans-category", "").strip()
                    if category not in DOMAINS:
                        category = infer_category(name + " " + metadata["description"])
                    modes = [
                        v.strip()
                        for v in extra.get(
                            "aitrans-context-modes", "general,reading"
                        ).split(",")
                    ]
                    result.append(
                        SkillDescriptor(
                            id=name,
                            description=metadata["description"],
                            category=category,
                            triggers=[
                                v.strip()[:128]
                                for v in extra.get("aitrans-triggers", "").split(",")
                                if v.strip()
                            ][:16],
                            context_modes=[
                                v for v in modes if v in {"general", "reading"}
                            ],
                            invocation="manual"
                            if extra.get("aitrans-invocation") == "manual"
                            else "auto",
                            revision=hashlib.sha256(repr(stamp).encode()).hexdigest(),
                        )
                    )
                except (SkillError, OSError, UnicodeError):
                    continue
            self._headers = {
                key: value for key, value in self._headers.items() if key in present
            }
            return result

    def runtime_entry(
        self, skill_id: str, revision: str
    ) -> tuple[SkillFileContent, list[SkillFile]]:
        with self._lock:
            current = next((d for d in self.descriptors() if d.id == skill_id), None)
            if current is None or current.revision != revision:
                raise SkillError("技能已停用、移除或更新，请重新发起任务。", 409)
            files = self._inventory(self._directory(skill_id))
            entry = self.read_file(skill_id, "SKILL.md")
            if entry.content is None or parse_manifest(entry.content, skill_id)[1]:
                raise SkillError("技能入口无效。", 409)
            # Detect atomic replacement during a read, including external edits.
            after = next((d for d in self.descriptors() if d.id == skill_id), None)
            if after is None or after.revision != revision:
                raise SkillError("技能读取期间发生更新，请重试。", 409)
            return entry, files

    def _directory(self, skill_id: str) -> Path:
        validate_name(skill_id)
        directory = self.root / skill_id
        if not directory.is_dir():
            raise SkillError("技能不存在。", 404)
        if _linked(directory) or directory.resolve().parent != self.root:
            raise SkillError("技能目录不能是符号链接或目录联接。")
        return directory

    def _file(self, directory: Path, value: str) -> Path:
        relative = _relative_path(value)
        if (
            relative.as_posix().casefold() == "skill.md"
            and relative.as_posix() != "SKILL.md"
        ):
            raise SkillError("入口文件必须使用准确的名称 SKILL.md。")
        path = directory / relative
        cursor = directory
        for part in relative.parts:
            cursor = cursor / part
            if (cursor.exists() or cursor.is_symlink()) and _linked(cursor):
                raise SkillError("不能访问符号链接或目录联接。")
        if not path.resolve().is_relative_to(directory.resolve()):
            raise SkillError("文件路径超出了技能目录。")
        return path

    def _inventory(self, directory: Path) -> list[SkillFile]:
        files = []
        seen = set()
        total = 0
        for current, directories, names in os.walk(directory, followlinks=False):
            directories[:] = sorted(d for d in directories if not d.startswith("."))
            for name in directories + names:
                path = Path(current) / name
                if name.startswith("."):
                    continue
                if _linked(path):
                    raise SkillError("技能包包含符号链接或目录联接。")
            for name in sorted(names):
                if name.startswith("."):
                    continue
                path = Path(current) / name
                relative = path.relative_to(directory).as_posix()
                _relative_path(relative)
                if relative.casefold() in seen:
                    raise SkillError(
                        "技能包包含仅大小写不同的重复文件名，无法安全导入。"
                    )
                seen.add(relative.casefold())
                if not path.is_file():
                    raise SkillError("技能包只能包含普通文件。")
                size = path.stat().st_size
                total += size
                files.append(SkillFile(path=relative, size=size))
                if (
                    size > MAX_FILE_BYTES
                    or total > MAX_SKILL_BYTES
                    or len(files) > MAX_FILES
                ):
                    raise SkillError(
                        "技能包超过限制：单文件 2 MB、总计 20 MB、最多 200 个文件。",
                        413,
                    )
        return sorted(files, key=lambda file: (file.path != "SKILL.md", file.path))

    def _state(self) -> dict:
        path = self.root / ".state.json"
        if not path.exists():
            return {}
        if _linked(path):
            raise SkillError("技能状态文件不能是符号链接。")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or any(
                not isinstance(v, bool) for v in state.values()
            ):
                raise ValueError
            return state
        except (ValueError, UnicodeError) as exc:
            raise SkillError(
                "技能状态文件损坏，请恢复 .state.json 后重试。", 409
            ) from exc

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temp.write_bytes(data)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def _write_state(self, state: dict) -> None:
        self._atomic_write(self.root / ".state.json", json.dumps(state).encode("utf-8"))

    def detail(self, skill_id: str) -> SkillDetail:
        with self._lock:
            directory = self._directory(skill_id)
            diagnostics = []
            metadata = {}
            try:
                files = self._inventory(directory)
            except SkillError as exc:
                files = []
                diagnostics.append(str(exc))
            try:
                manifest = self.read_file(skill_id, "SKILL.md")
                if manifest.content is None:
                    diagnostics.append("SKILL.md 必须是 UTF-8 文本。")
                else:
                    metadata, issues = parse_manifest(manifest.content, skill_id)
                    diagnostics.extend(issues)
            except SkillError as exc:
                diagnostics.append(str(exc))
            modified = max(
                [directory.stat().st_mtime]
                + [(directory / file.path).stat().st_mtime for file in files]
            )
            return SkillDetail(
                id=skill_id,
                name=metadata.get("name")
                if isinstance(metadata.get("name"), str)
                else skill_id,
                description=metadata.get("description")
                if isinstance(metadata.get("description"), str)
                else "",
                enabled=self._state().get(skill_id, False) and not diagnostics,
                valid=not diagnostics,
                diagnostics=diagnostics,
                metadata=metadata,
                files=files,
                file_count=len(files),
                updated_at=datetime.fromtimestamp(modified, UTC).isoformat(),
            )

    def list(self) -> SkillLibrary:
        with self._lock:
            records = []
            for directory in sorted(self.root.iterdir()):
                if (
                    directory.name.startswith(".")
                    or not directory.is_dir()
                    or _linked(directory)
                ):
                    continue
                try:
                    records.append(self.detail(directory.name))
                except SkillError as exc:
                    if exc.status == 409:
                        raise
            return SkillLibrary(skills=records, storage_root=str(self.root))

    def _install(self, name: str, populate) -> SkillDetail:
        validate_name(name)
        with self._lock:
            destination = self.root / name
            if destination.exists() or destination.is_symlink():
                raise SkillError("同名技能已存在，请更改名称或移除旧版本。", 409)
            staging = self.root / f".import-{uuid4().hex}"
            staging.mkdir()
            try:
                populate(staging)
                self._inventory(staging)
                state = self._state()
                state[name] = False
                self._write_state(state)
                os.rename(staging, destination)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            return self.detail(name)

    def create(self, name: str, description: str) -> SkillDetail:
        if not description.strip():
            raise SkillError("请填写技能用途。")
        manifest = yaml.safe_dump(
            {"name": name, "description": description.strip()},
            allow_unicode=True,
            sort_keys=False,
        )
        content = f"---\n{manifest}---\n\n# {name}\n\n## 使用时机\n\n{description.strip()}\n\n## 执行步骤\n\n1. 确认输入与目标。\n2. 按照任务要求完成操作。\n3. 检查结果并说明限制。\n"
        return self._install(
            name,
            lambda target: (target / "SKILL.md").write_text(content, encoding="utf-8"),
        )

    def import_skill(
        self, *, path: str | None = None, content: str | None = None
    ) -> SkillDetail:
        if content is not None:
            metadata, _ = parse_manifest(content, "")
            name = metadata.get("name")
            if not isinstance(name, str):
                raise SkillError("导入的 SKILL.md 必须包含有效的 name 字段。")
            return self._install(
                name,
                lambda target: (target / "SKILL.md").write_text(
                    content, encoding="utf-8"
                ),
            )
        if not path:
            raise SkillError("请选择技能目录。")
        source = Path(path).expanduser()
        if not source.is_dir() or _linked(source):
            raise SkillError("请选择包含 SKILL.md 的普通目录。")
        source = source.resolve()
        files = self._inventory(source)
        if not any(file.path == "SKILL.md" for file in files):
            raise SkillError("目录根部缺少 SKILL.md。")

        def populate(target: Path):
            for file in files:
                original = self._file(source, file.path)
                output = target / file.path
                output.parent.mkdir(parents=True, exist_ok=True)
                # Bounded read also handles source files growing during import.
                with original.open("rb") as handle:
                    data = handle.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise SkillError("导入文件超过 2 MB。", 413)
                output.write_bytes(data)

        return self._install(source.name, populate)

    def read_file(self, skill_id: str, path: str) -> SkillFileContent:
        with self._lock:
            file = self._file(self._directory(skill_id), path)
            if not file.is_file():
                raise SkillError("文件不存在。", 404)
            with file.open("rb") as handle:
                data = handle.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise SkillError("文件超过 2 MB，无法在线预览。", 413)
            try:
                content = data.decode("utf-8-sig") if b"\x00" not in data else None
            except UnicodeError:
                content = None
            return SkillFileContent(
                path=path,
                size=len(data),
                content=content,
                revision=hashlib.sha256(data).hexdigest(),
                language="markdown"
                if file.suffix.lower() in {".md", ".markdown"}
                else file.suffix.lstrip(".") or "text",
                previewable=content is not None,
            )

    def write_file(
        self, skill_id: str, path: str, content: str, revision: str | None
    ) -> SkillFileContent:
        with self._lock:
            directory = self._directory(skill_id)
            file = self._file(directory, path)
            if file.exists():
                current = self.read_file(skill_id, path)
                if current.revision != revision:
                    raise SkillError(
                        "文件已更改，请重新加载后再保存。你的修改尚未覆盖磁盘文件。",
                        409,
                    )
            elif revision is not None:
                raise SkillError("文件已被删除，请重新加载。", 409)
            data = content.encode("utf-8")
            files = self._inventory(directory)
            previous = next((item.size for item in files if item.path == path), 0)
            if (
                len(data) > MAX_FILE_BYTES
                or sum(item.size for item in files) - previous + len(data)
                > MAX_SKILL_BYTES
                or len(files) + int(not file.exists()) > MAX_FILES
            ):
                raise SkillError("写入将超过技能包大小或文件数量限制。", 413)
            # Invalid edits may be saved as drafts but must deactivate the skill.
            if path == "SKILL.md":
                _, diagnostics = parse_manifest(content, skill_id)
                if diagnostics:
                    state = self._state()
                    state[skill_id] = False
                    self._write_state(state)
            file.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(file, data)
            return self.read_file(skill_id, path)

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillDetail:
        with self._lock:
            record = self.detail(skill_id)
            if enabled and not record.valid:
                raise SkillError("技能格式校验未通过，请先修复 SKILL.md。", 409)
            state = self._state()
            state[skill_id] = enabled
            self._write_state(state)
            return self.detail(skill_id)

    def delete_file(self, skill_id: str, path: str, revision: str) -> None:
        with self._lock:
            if _relative_path(path).as_posix() == "SKILL.md":
                raise SkillError("不能删除入口文件 SKILL.md；可移除整个技能。")
            current = self.read_file(skill_id, path)
            if current.revision != revision:
                raise SkillError("文件已更改，请重新加载后再删除。", 409)
            self._file(self._directory(skill_id), path).unlink()

    def remove(self, skill_id: str) -> str:
        with self._lock:
            directory = self._directory(skill_id)
            trash = self.root / ".trash"
            if trash.exists() and _linked(trash):
                raise SkillError("回收目录不能是符号链接或目录联接。")
            trash.mkdir(exist_ok=True)
            target = trash / f"{skill_id}-{uuid4().hex}"
            state = self._state()
            state.pop(skill_id, None)
            self._write_state(state)
            os.rename(directory, target)
            return str(target)
