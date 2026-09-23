from __future__ import annotations

import json

from backend.rag.benchmarks.qasper import (
    align_qasper_evidence,
    load_qasper,
    map_gold_paragraphs_to_chunks,
)
from backend.rag.benchmarks.qasper.index import build_qasper_index
from backend.rag.config import RagConfig, RagEmbeddingConfig


class _FakeEmbedding:
    dimension = 2
    model_name = "test-qasper-embedding"

    def __init__(self) -> None:
        self.document_batches = 0

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_batches += 1
        return [[1.0, 0.0] for _ in texts]


class _FakeReranker:
    def rerank(self, _query, candidates, *, top_k):
        return candidates[:top_k]


def _dataset(tmp_path):
    raw_path = tmp_path / "index-sample.json"
    paragraph_one = "The system retrieves evidence before answering questions."
    paragraph_two = "A second paragraph contains the reported evaluation result."
    raw_path.write_text(
        json.dumps(
            {
                "paper-index": {
                    "title": "Index paper",
                    "abstract": "The paper studies evidence retrieval.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [paragraph_one, paragraph_two],
                        }
                    ],
                    "qas": [
                        {
                            "question_id": "q-index",
                            "question": "What does the system retrieve?",
                            "answers": [
                                {
                                    "annotation_id": "a-index",
                                    "answer": {"free_form_answer": "Evidence."},
                                    "evidence": [paragraph_one],
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return load_qasper(raw_path)


def test_indexer_attaches_gold_paragraph_ids_and_reuses_query_time_cache(tmp_path) -> None:
    dataset = _dataset(tmp_path)
    embedding = _FakeEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(model=embedding.model_name, dimension=embedding.dimension)
    )
    first = build_qasper_index(
        dataset,
        storage_root=tmp_path / "benchmark",
        config=config,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
    )
    try:
        assert not first.result.cache_hit
        chunks = first.runtime.sparse_retriever.list_chunks()
        paragraph_ids = {
            paragraph_id
            for chunk in chunks
            for paragraph_id in chunk.metadata["benchmark"]["source_paragraph_ids"]
        }
        expected_ids = {paragraph.paragraph_id for paragraph in dataset.papers["paper-index"].paragraphs}
        assert paragraph_ids == expected_ids
        alignment = align_qasper_evidence(dataset)
        gold_paragraph_ids = list(
            alignment.by_question["q-index"][0].paragraph_ids
        )
        gold_chunks = map_gold_paragraphs_to_chunks(gold_paragraph_ids, chunks)
        assert gold_chunks
        assert first.runtime.vector_store.count_chunks() == first.result.chunk_count
        assert first.runtime.sparse_retriever.list_chunks()
    finally:
        first.close()

    query_variant = config.model_copy(deep=True)
    query_variant.retrieval = query_variant.retrieval.model_copy(
        update={"dense_top_k": 12, "sparse_top_k": 12, "fusion_top_k": 10, "final_top_k": 5}
    )
    second = build_qasper_index(
        dataset,
        storage_root=tmp_path / "benchmark",
        config=query_variant,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
    )
    try:
        assert second.result.cache_hit
        assert second.result.fingerprint == first.result.fingerprint
        assert embedding.document_batches == 1
        assert second.runtime.config.retrieval.dense_top_k == 12
    finally:
        second.close()

    manifest = json.loads(first.result.index_manifest_path.read_text(encoding="utf-8"))
    manifest["document_chunk_ids"] = {}
    first.result.index_manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    repaired = build_qasper_index(
        dataset,
        storage_root=tmp_path / "benchmark",
        config=query_variant,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
    )
    try:
        assert not repaired.result.cache_hit
        assert repaired.result.reused_paper_count == 1
        assert repaired.result.indexed_paper_count == 0
        assert embedding.document_batches == 1
    finally:
        repaired.close()
