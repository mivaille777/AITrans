from __future__ import annotations

from typing import Any

import pytest

from backend.rag.config import RagRerankerConfig
from backend.rag.exceptions import RagRetrievalError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.rerankers.qwen3 import Qwen3RerankerProvider


class Torch:
    class cuda:
        @staticmethod
        def is_available():
            return False


class Model:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return self.scores


def candidates():
    return [
        RetrievalCandidate(
            chunk=DocumentChunk(
                chunk_id=f"chunk_{index}",
                document_id="doc",
                text=text,
                chunk_index=index,
            ),
            fusion_score=0.1,
            rank=index + 1,
        )
        for index, text in enumerate(["first", "second", "third"])
    ]


def provider(model, calls, **config):
    def factory(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return model

    return Qwen3RerankerProvider(
        RagRerankerConfig(**config), model_factory=factory, torch_module=Torch()
    )


def test_pair_construction_score_mapping_sort_and_top_k() -> None:
    model = Model([0.2, 0.9, 0.5])
    calls = []
    reranker = provider(model, calls, batch_size=4)

    results = reranker.rerank("query", candidates(), top_k=2)

    assert [item.chunk.chunk_id for item in results] == ["chunk_1", "chunk_2"]
    assert [item.rerank_score for item in results] == [0.9, 0.5]
    assert model.calls[0][0] == [
        ("query", "Type: paragraph_group\nContent:\nfirst"),
        ("query", "Type: paragraph_group\nContent:\nsecond"),
        ("query", "Type: paragraph_group\nContent:\nthird"),
    ]
    assert model.calls[0][1]["batch_size"] == 4


def test_pair_includes_document_hierarchy_type_labels_and_page_metadata() -> None:
    model = Model([0.8])
    reranker = provider(model, [])
    candidate = RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id="references-1",
            document_id="wen-paper",
            title="Water Tank Paper",
            section_heading="References",
            section_path=["6 References"],
            chunk_type="reference_group",
            page_number=11,
            text="[1] A. Author, Example reference.",
            chunk_index=0,
            metadata={"special_labels": ["[1]"]},
        ),
        rank=1,
    )

    reranker.rerank("Which references were cited?", [candidate], top_k=1)

    assert model.calls[0][0] == [
        (
            "Which references were cited?",
            "Document: Water Tank Paper\n"
            "Hierarchy: 6 References\n"
            "Type: reference_group\n"
            "Labels: [1]\n"
            "Page: 11\n"
            "Content:\n[1] A. Author, Example reference.",
        )
    ]


def test_model_loads_once_and_ties_are_stable() -> None:
    model = Model([1.0, 1.0, 0.0])
    calls = []
    reranker = provider(model, calls)

    first = reranker.rerank("query", candidates(), top_k=3)
    reranker.rerank("query", candidates(), top_k=3)

    assert len(calls) == 1
    assert [item.chunk.chunk_id for item in first[:2]] == ["chunk_0", "chunk_1"]


def test_invalid_scores_are_rejected() -> None:
    reranker = provider(Model([0.1]), [])
    with pytest.raises(RagRetrievalError, match="count mismatch"):
        reranker.rerank("query", candidates(), top_k=2)
