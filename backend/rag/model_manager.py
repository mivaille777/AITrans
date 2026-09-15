from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

from app.infrastructure.paths import data_root
from backend.models.rag_runtime import (
    RagModelId,
    RagModelSource,
    RagModelStatusResponse,
)
from backend.rag.exceptions import RagModelManagerError

MODELS_DIRECTORY_ENVIRONMENT_VARIABLE = "AITRANS_MODELS_DIR"
MODEL_COMPLETION_MANIFEST = ".aitrans-model.json"
EMBEDDING_MODEL_ID: RagModelId = "qwen3-embedding-0.6b"
RERANKER_MODEL_ID: RagModelId = "qwen3-reranker-0.6b"

SnapshotDownloader = Callable[..., Any]
SnapshotResolver = Callable[..., str | Path]


@dataclass(frozen=True, slots=True)
class RagManagedModelSpec:
    model_id: RagModelId
    display_name: str
    repository_id: str
    directory_name: str
    required_files: tuple[str, ...]
    required_any: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class RagModelResolution:
    path: Path
    source: RagModelSource
    error: str


MODEL_SPECS: dict[RagModelId, RagManagedModelSpec] = {
    EMBEDDING_MODEL_ID: RagManagedModelSpec(
        model_id=EMBEDDING_MODEL_ID,
        display_name="Qwen3 Embedding 0.6B",
        repository_id="Qwen/Qwen3-Embedding-0.6B",
        directory_name="qwen3-embedding-0.6b",
        required_files=("config.json", "modules.json", "tokenizer_config.json"),
        required_any=(
            (
                "model.safetensors",
                "model.safetensors.index.json",
                "pytorch_model.bin",
            ),
        ),
    ),
    RERANKER_MODEL_ID: RagManagedModelSpec(
        model_id=RERANKER_MODEL_ID,
        display_name="Qwen3 Reranker 0.6B",
        repository_id="Qwen/Qwen3-Reranker-0.6B",
        directory_name="qwen3-reranker-0.6b",
        required_files=("config.json", "tokenizer_config.json"),
        required_any=(
            (
                "model.safetensors",
                "model.safetensors.index.json",
                "pytorch_model.bin",
            ),
        ),
    ),
}


def default_models_root() -> Path:
    configured = os.getenv(MODELS_DIRECTORY_ENVIRONMENT_VARIABLE, "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "AITrans" / "models"
    return data_root() / "models"


def _default_downloader(**kwargs: Any) -> Any:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RagModelManagerError(
            "huggingface-hub is required to download managed RAG models"
        ) from exc
    return snapshot_download(**kwargs)


class ModelManager:
    def __init__(
        self,
        models_root: str | Path | None = None,
        *,
        downloader: SnapshotDownloader | None = None,
        cache_resolver: SnapshotResolver | None = None,
    ) -> None:
        self.models_root = (
            Path(models_root or default_models_root()).expanduser().resolve()
        )
        self._downloader = downloader or _default_downloader
        self._cache_resolver = cache_resolver or _default_downloader
        self._state_lock = Lock()
        self._active_downloads: set[RagModelId] = set()
        self._operation_locks = {model_id: RLock() for model_id in MODEL_SPECS}

    @staticmethod
    def model_ids() -> tuple[RagModelId, ...]:
        return tuple(MODEL_SPECS)

    def _spec(self, model_id: str) -> RagManagedModelSpec:
        try:
            return MODEL_SPECS[model_id]  # type: ignore[index]
        except KeyError as exc:
            raise RagModelManagerError(
                f"unknown managed RAG model: {model_id}"
            ) from exc

    def _target(self, spec: RagManagedModelSpec) -> Path:
        target = (self.models_root / spec.directory_name).resolve()
        if target.parent != self.models_root:
            raise RagModelManagerError(
                "managed model path escaped the models directory"
            )
        return target

    @staticmethod
    def _nonempty_file(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def _verification_error(
        self,
        spec: RagManagedModelSpec,
        path: Path,
        *,
        require_manifest: bool,
    ) -> str:
        if not path.is_dir():
            return "model directory does not exist"
        missing = [
            relative
            for relative in spec.required_files
            if not self._nonempty_file(path / relative)
        ]
        if missing:
            return f"missing required file: {missing[0]}"
        for alternatives in spec.required_any:
            if not any(self._nonempty_file(path / item) for item in alternatives):
                return f"missing required model artifact: {' or '.join(alternatives)}"
        if require_manifest:
            manifest_path = path / MODEL_COMPLETION_MANIFEST
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return "missing or invalid completion manifest"
            if payload.get("model_id") != spec.model_id:
                return "completion manifest model_id mismatch"
            if payload.get("repository_id") != spec.repository_id:
                return "completion manifest repository_id mismatch"
        return ""

    def _cached_target(self, spec: RagManagedModelSpec) -> Path | None:
        try:
            cached = self._cache_resolver(
                repo_id=spec.repository_id,
                local_files_only=True,
            )
            if not cached:
                return None
            return Path(cached).expanduser().resolve()
        except Exception:  # noqa: BLE001 - cache discovery must remain offline and optional
            return None

    def _resolve_model(self, spec: RagManagedModelSpec) -> RagModelResolution:
        managed = self._target(spec)
        if managed.exists():
            return RagModelResolution(
                path=managed,
                source="managed",
                error=self._verification_error(
                    spec,
                    managed,
                    require_manifest=True,
                ),
            )

        cached = self._cached_target(spec)
        if cached is not None:
            return RagModelResolution(
                path=cached,
                source="huggingface_cache",
                error=self._verification_error(
                    spec,
                    cached,
                    require_manifest=False,
                ),
            )

        return RagModelResolution(
            path=managed,
            source="none",
            error="model directory does not exist",
        )

    def is_installed(self, model_id: str) -> bool:
        return self.verify(model_id)

    def get_model_path(self, model_id: str) -> Path:
        spec = self._spec(model_id)
        resolution = self._resolve_model(spec)
        if resolution.error:
            raise RagModelManagerError(
                f"{spec.display_name} is not installed: {resolution.error}"
            )
        return resolution.path

    def verify(self, model_id: str) -> bool:
        spec = self._spec(model_id)
        return not self._resolve_model(spec).error

    def download(self, model_id: str) -> Path:
        spec = self._spec(model_id)
        target = self._target(spec)
        with self._operation_locks[spec.model_id]:
            resolution = self._resolve_model(spec)
            if not resolution.error:
                return resolution.path
            if target.exists():
                raise RagModelManagerError(
                    f"invalid model directory already exists: {target}; remove it before downloading"
                )
            self.models_root.mkdir(parents=True, exist_ok=True)
            partial = (
                self.models_root / f".{spec.directory_name}.partial-{uuid4().hex}"
            ).resolve()
            if partial.parent != self.models_root:
                raise RagModelManagerError(
                    "partial model path escaped the models directory"
                )
            with self._state_lock:
                self._active_downloads.add(spec.model_id)
            try:
                partial.mkdir(parents=False, exist_ok=False)
                self._downloader(
                    repo_id=spec.repository_id,
                    local_dir=str(partial),
                )
                error = self._verification_error(
                    spec,
                    partial,
                    require_manifest=False,
                )
                if error:
                    raise RagModelManagerError(
                        f"downloaded model failed verification: {error}"
                    )
                (partial / MODEL_COMPLETION_MANIFEST).write_text(
                    json.dumps(
                        {
                            "model_id": spec.model_id,
                            "repository_id": spec.repository_id,
                            "completed_at": datetime.now(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                partial.replace(target)
                if not self.verify(spec.model_id):
                    raise RagModelManagerError(
                        "model failed verification after atomic installation"
                    )
                return target
            except RagModelManagerError:
                raise
            except Exception as exc:
                raise RagModelManagerError(
                    f"failed to download {spec.display_name}: {exc}"
                ) from exc
            finally:
                with self._state_lock:
                    self._active_downloads.discard(spec.model_id)
                if partial.exists():
                    self._remove_tree(partial)

    def remove(self, model_id: str) -> bool:
        spec = self._spec(model_id)
        target = self._target(spec)
        with self._operation_locks[spec.model_id]:
            if target.exists():
                self._remove_tree(target)
                return True
            if self._cached_target(spec) is not None:
                raise RagModelManagerError(
                    "refusing to remove a shared Hugging Face cache model"
                )
            return False

    def _remove_tree(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved.parent != self.models_root or resolved == self.models_root:
            raise RagModelManagerError(
                "refusing to remove path outside models directory"
            )
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            raise RagModelManagerError(
                f"failed to remove model path: {resolved}"
            ) from exc

    @staticmethod
    def _disk_usage(path: Path) -> int:
        if not path.is_dir():
            return 0
        total = 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
        except OSError as exc:
            raise RagModelManagerError(
                f"failed to inspect model path: {path}"
            ) from exc
        return total

    def disk_usage(self, model_id: str) -> int:
        resolution = self._resolve_model(self._spec(model_id))
        return 0 if resolution.source == "none" else self._disk_usage(resolution.path)

    def status(self, model_id: str) -> RagModelStatusResponse:
        spec = self._spec(model_id)
        resolution = self._resolve_model(spec)
        with self._state_lock:
            downloading = spec.model_id in self._active_downloads
        installed = not resolution.error
        if downloading:
            state = "downloading"
        elif installed:
            state = "installed"
        elif resolution.source != "none":
            state = "invalid"
        else:
            state = "not_installed"
        source: RagModelSource = "managed" if downloading else resolution.source
        return RagModelStatusResponse(
            model_id=spec.model_id,
            display_name=spec.display_name,
            repository_id=spec.repository_id,
            state=state,
            installed=installed,
            verified=installed,
            source=source,
            removable=source == "managed" and not downloading,
            path=str(resolution.path) if resolution.source != "none" else "",
            disk_usage_bytes=(
                self._disk_usage(resolution.path)
                if resolution.source != "none"
                else 0
            ),
            error=resolution.error if state == "invalid" else "",
        )

    def statuses(self) -> list[RagModelStatusResponse]:
        return [self.status(model_id) for model_id in self.model_ids()]


__all__ = [
    "EMBEDDING_MODEL_ID",
    "MODELS_DIRECTORY_ENVIRONMENT_VARIABLE",
    "MODEL_COMPLETION_MANIFEST",
    "MODEL_SPECS",
    "RERANKER_MODEL_ID",
    "ModelManager",
    "RagManagedModelSpec",
    "RagModelResolution",
    "SnapshotResolver",
    "default_models_root",
]
