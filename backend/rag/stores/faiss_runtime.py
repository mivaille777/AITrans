"""GPU-preferred FAISS indexes with the same durable IDs and a CPU safety net."""

from __future__ import annotations

import logging
import os
from threading import RLock

import faiss
import numpy as np

from backend.rag.exceptions import RagConfigurationError

logger = logging.getLogger(__name__)
_gpu_lock = RLock()
_resources: dict[tuple[int, int], object] = {}
GPU_MAX_K = 2048


class LocalFaissIndex:
    """Keep a CPU index; serialize shared CUDA resources across repositories.

    GPU Flat returns positional IDs, which are translated to SQLite's stable
    int64 IDs. Neither the GPU index nor its resources are persisted to disk.
    """

    def __init__(self, matrix: np.ndarray, ids: np.ndarray, distance: str):
        dimension = matrix.shape[1]
        if distance in {"dot", "cosine"}:
            flat = faiss.IndexFlatIP(dimension)
        elif distance == "euclid":
            flat = faiss.IndexFlatL2(dimension)
        elif distance == "manhattan":
            flat = faiss.IndexFlat(dimension, faiss.METRIC_L1)
        else:
            raise RagConfigurationError(f"unsupported vector distance: {distance!r}")
        self.ids = np.asarray(ids, dtype=np.int64).copy()
        self.cpu = faiss.IndexIDMap2(flat)
        if len(matrix):
            self.cpu.add_with_ids(
                np.ascontiguousarray(matrix, dtype=np.float32), self.ids
            )
        self.gpu = None
        self.device_id = None
        self.fallback_reason = ""
        self.last_search_device = "cpu"
        preference = os.environ.get("AITRANS_FAISS_DEVICE", "auto").lower()
        if preference not in {"auto", "cpu"}:
            raise RagConfigurationError("AITRANS_FAISS_DEVICE must be auto or cpu")
        if preference == "cpu":
            self.fallback_reason = "cpu_requested"
        elif distance == "manhattan":
            self.fallback_reason = "metric_requires_cpu"
        elif not len(matrix):
            self.fallback_reason = "empty_index"
        elif not hasattr(faiss, "StandardGpuResources"):
            self.fallback_reason = "gpu_build_unavailable"
        else:
            try:
                device = int(os.environ.get("AITRANS_FAISS_GPU_DEVICE", "0"))
                with _gpu_lock:
                    if not 0 <= device < faiss.get_num_gpus():
                        self.fallback_reason = "gpu_device_unavailable"
                        return
                    key = (os.getpid(), device)
                    if key not in _resources:
                        resource = faiss.StandardGpuResources()
                        # Leave VRAM for Qwen/ColQwen; FAISS defaults to ~1 GiB.
                        resource.setTempMemory(64 * 1024 * 1024)
                        _resources[key] = resource
                    self.gpu = faiss.index_cpu_to_gpu(_resources[key], device, flat)
                    self.device_id = device
            except Exception as exc:  # noqa: BLE001 - any CUDA failure must preserve CPU retrieval
                self._disable_gpu("gpu_initialization_failed", exc)

    @property
    def device(self) -> str:
        return "cuda" if self.gpu is not None else "cpu"

    def diagnostics(self) -> dict:
        return {
            "device": self.device,
            "gpu_device": self.device_id,
            "last_search_device": self.last_search_device,
            "fallback_reason": self.fallback_reason,
        }

    def _disable_gpu(self, reason: str, exc: Exception) -> None:
        self.gpu = None
        self.device_id = None
        self.fallback_reason = reason
        logger.warning("FAISS GPU unavailable; using CPU (%s): %s", reason, exc)

    def search(self, query: np.ndarray, count: int):
        query = np.ascontiguousarray(query, dtype=np.float32)
        with _gpu_lock:
            if self.gpu is not None and count <= GPU_MAX_K:
                try:
                    scores, positions = self.gpu.search(query, count)
                    ids = np.full(positions.shape, -1, dtype=np.int64)
                    valid = positions >= 0
                    ids[valid] = self.ids[positions[valid]]
                    self.last_search_device = "cuda"
                    self.fallback_reason = ""
                    return scores, ids
                except Exception as exc:  # noqa: BLE001 - native wrapper errors vary by FAISS build
                    self._disable_gpu("gpu_search_failed", exc)
            elif self.gpu is not None:
                # Large top-k and deterministic boundary-tie expansion exceed
                # CUDA Flat's limit; keep the GPU available for later queries.
                self.fallback_reason = "gpu_top_k_limit"
            self.last_search_device = "cpu"
            return self.cpu.search(query, count)


def make_index(matrix: np.ndarray, ids: np.ndarray, distance: str) -> LocalFaissIndex:
    return LocalFaissIndex(matrix, ids, distance)
