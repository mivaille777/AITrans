from __future__ import annotations

import os

import pytest

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider

pytestmark = pytest.mark.rag_gpu


def _dot(left: list[float], right: list[float]) -> float:
    return sum(first * second for first, second in zip(left, right, strict=True))


@pytest.mark.skipif(
    os.environ.get("AITRANS_RUN_RAG_GPU_TESTS") != "1",
    reason="set AITRANS_RUN_RAG_GPU_TESTS=1 to load the real Qwen3 embedding model",
)
def test_qwen3_embedding_real_cuda_semantics() -> None:
    import torch

    assert torch.cuda.is_available()
    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(device="cuda", warmup=True, batch_size=8)
    )

    query = provider.embed_query("如何用高斯过程优化 PID 参数？")
    documents = provider.embed_documents(
        [
            "高斯过程可以构建代理模型，并通过贝叶斯优化搜索 PID 控制器参数。",
            "卷积神经网络常用于图像识别和目标检测。",
        ]
    )

    assert len(query) == 1024
    assert [len(vector) for vector in documents] == [1024, 1024]
    assert _dot(query, documents[0]) > _dot(query, documents[1])
