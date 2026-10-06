from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import faiss
import numpy as np
import pytest

from backend.rag.stores import faiss_runtime as runtime


def matrix_and_ids(count=3):
    return np.eye(count, dtype=np.float32), np.arange(count, dtype=np.int64) + 100


def test_cpu_build_and_no_device_fallback(monkeypatch):
    monkeypatch.setenv("AITRANS_FAISS_DEVICE", "auto")
    monkeypatch.delattr(faiss, "StandardGpuResources", raising=False)
    matrix, ids = matrix_and_ids()
    index = runtime.make_index(matrix, ids, "dot")
    assert index.diagnostics()["fallback_reason"] == "gpu_build_unavailable"
    scores, found = index.search(matrix[:1], 2)
    assert found[0, 0] == 100
    assert scores[0, 0] == 1


def test_no_gpu_and_initialization_error_fallback(monkeypatch):
    monkeypatch.setenv("AITRANS_FAISS_DEVICE", "auto")
    monkeypatch.setattr(faiss, "StandardGpuResources", lambda: None, raising=False)
    monkeypatch.setattr(faiss, "get_num_gpus", lambda: 0, raising=False)
    matrix, ids = matrix_and_ids()
    index = runtime.make_index(matrix, ids, "dot")
    assert index.fallback_reason == "gpu_device_unavailable"

    monkeypatch.setattr(faiss, "get_num_gpus", lambda: 1)
    def fail(*_args):
        raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(faiss, "index_cpu_to_gpu", fail, raising=False)
    index = runtime.make_index(matrix, ids, "dot")
    assert index.device == "cpu"
    assert index.search(matrix[:1], 1)[1][0, 0] == 100


def test_search_error_falls_back_and_keeps_ids(monkeypatch):
    monkeypatch.setenv("AITRANS_FAISS_DEVICE", "cpu")
    matrix, ids = matrix_and_ids()
    index = runtime.make_index(matrix, ids, "dot")
    class BrokenGpu:
        def search(self, *_args):
            raise RuntimeError("GPU lost")
    index.gpu = BrokenGpu()
    scores, found = index.search(matrix[:1], 2)
    assert found[0, 0] == 100
    assert scores[0, 0] == 1
    assert index.device == "cpu"
    assert index.fallback_reason == "gpu_search_failed"


def test_large_top_k_uses_cpu_without_disabling_gpu(monkeypatch):
    monkeypatch.setenv("AITRANS_FAISS_DEVICE", "cpu")
    matrix = np.ones((2050, 2), dtype=np.float32)
    index = runtime.make_index(matrix, np.arange(2050) + 100, "dot")
    class UnexpectedGpu:
        def search(self, *_args):
            pytest.fail("top-k above 2048 must not reach GPU")
    index.gpu = UnexpectedGpu()
    _, ids = index.search(matrix[:1], 2050)
    assert set(ids[0]) == set(range(100, 2150))
    assert index.device == "cuda"
    assert index.last_search_device == "cpu"
    assert index.fallback_reason == "gpu_top_k_limit"


@pytest.mark.rag_gpu
@pytest.mark.parametrize("distance", ["dot", "cosine", "euclid"])
def test_real_gpu_matches_cpu_and_shared_resources_are_safe(monkeypatch, distance):
    if not hasattr(faiss, "StandardGpuResources") or not faiss.get_num_gpus():
        pytest.skip("FAISS GPU build and an available CUDA device are required")
    rng = np.random.default_rng(42)
    matrix = rng.normal(size=(3000, 128)).astype(np.float32)
    queries = rng.normal(size=(8, 128)).astype(np.float32)
    if distance == "cosine":
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    ids = np.arange(3000, dtype=np.int64) * 7 + 10000
    monkeypatch.setenv("AITRANS_FAISS_DEVICE", "cpu")
    cpu = runtime.make_index(matrix, ids, distance)
    monkeypatch.setenv("AITRANS_FAISS_DEVICE", "auto")
    gpu = runtime.make_index(matrix, ids, distance)
    another = runtime.make_index(matrix, ids, distance)
    assert gpu.device == another.device == "cuda"
    expected_scores, expected_ids = cpu.search(queries, 20)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: (gpu if i % 2 else another).search(queries, 20), range(12)))
    for scores, found in results:
        np.testing.assert_array_equal(found, expected_ids)
        np.testing.assert_allclose(scores, expected_scores, rtol=2e-5, atol=2e-5)
    assert gpu.last_search_device == "cuda"
    # A large search falls back and a subsequent ordinary query uses GPU again.
    gpu.search(queries[:1], 2050)
    assert gpu.last_search_device == "cpu"
    gpu.search(queries[:1], 20)
    assert gpu.last_search_device == "cuda"
