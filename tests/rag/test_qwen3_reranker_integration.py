import os

import pytest

from backend.rag.config import RagRerankerConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.rerankers.qwen3 import Qwen3RerankerProvider

pytestmark = pytest.mark.rag_gpu


@pytest.mark.skipif(
    os.environ.get("AITRANS_RUN_RAG_GPU_TESTS") != "1",
    reason="set AITRANS_RUN_RAG_GPU_TESTS=1 to load the real Qwen3 reranker",
)
def test_qwen3_reranker_real_cuda_semantics() -> None:
    provider = Qwen3RerankerProvider(RagRerankerConfig(device="cuda"))
    candidates = [
        RetrievalCandidate(
            chunk=DocumentChunk(
                chunk_id=f"chunk_{index}",
                document_id="doc",
                text=text,
                chunk_index=index,
            ),
            rank=index + 1,
        )
        for index, text in enumerate(
            ["高斯过程可以优化PID参数。", "卷积网络用于图像识别。"]
        )
    ]
    results = provider.rerank("如何优化PID参数？", candidates, top_k=2)
    assert results[0].chunk.chunk_id == "chunk_0"
