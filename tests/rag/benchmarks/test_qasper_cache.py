from __future__ import annotations

import json

from backend.rag.benchmarks.cache import (
    build_index_cache_fingerprint,
    qasper_sample_hash,
)
from backend.rag.benchmarks.qasper.loader import load_qasper
from backend.rag.config import RagConfig, RagEmbeddingConfig


def _dataset(tmp_path):
    path = tmp_path / "cache-sample.json"
    path.write_text(
        json.dumps(
            {
                "paper-cache": {
                    "title": "Cache paper",
                    "abstract": "A short abstract.",
                    "full_text": [
                        {"section_name": "Results", "paragraphs": ["A result paragraph."]}
                    ],
                    "qas": [
                        {
                            "question_id": "q-cache",
                            "question": "What is reported?",
                            "answers": [
                                {
                                    "annotation_id": "a-cache",
                                    "answer": {"free_form_answer": "A result."},
                                    "evidence": ["A result paragraph."],
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return load_qasper(path)


def test_index_fingerprint_excludes_query_time_settings(tmp_path) -> None:
    dataset = _dataset(tmp_path)
    baseline = RagConfig(embedding=RagEmbeddingConfig(model="test-model", dimension=2))
    query_variant = baseline.model_copy(deep=True)
    query_variant.retrieval = query_variant.retrieval.model_copy(
        update={
            "dense_top_k": 10,
            "sparse_top_k": 10,
            "fusion_top_k": 8,
            "final_top_k": 4,
            "small_to_big_enabled": False,
        }
    )
    query_variant.reranker = query_variant.reranker.model_copy(
        update={"model": "a-query-time-reranker"}
    )

    baseline_fingerprint = build_index_cache_fingerprint(dataset, baseline)
    query_fingerprint = build_index_cache_fingerprint(dataset, query_variant)

    assert baseline_fingerprint.digest == query_fingerprint.digest
    assert qasper_sample_hash(dataset) == baseline_fingerprint.sample_hash


def test_chunking_and_embedding_settings_change_index_fingerprint(tmp_path) -> None:
    dataset = _dataset(tmp_path)
    base = RagConfig(embedding=RagEmbeddingConfig(model="test-model", dimension=2))
    changed_chunking = base.model_copy(deep=True)
    changed_chunking.chunking = changed_chunking.chunking.model_copy(
        update={"target_tokens": 400, "minimum_tokens": 80}
    )
    changed_embedding = base.model_copy(deep=True)
    changed_embedding.embedding = changed_embedding.embedding.model_copy(
        update={"dimension": 4}
    )

    digest = build_index_cache_fingerprint(dataset, base).digest
    assert digest != build_index_cache_fingerprint(dataset, changed_chunking).digest
    assert digest != build_index_cache_fingerprint(dataset, changed_embedding).digest
