from __future__ import annotations

import json

from backend.rag.benchmarks.qasper.loader import load_qasper
from backend.rag.benchmarks.qasper.runner import (
    GroundedQasperAnswerer,
    QasperGeneratedAnswer,
    run_qasper_benchmark,
)
from backend.rag.benchmarks.qasper.sampling import sample_qasper_dataset
from backend.rag.config import RagConfig, RagEmbeddingConfig
from backend.rag.models import RetrievalResult


class _FakeEmbedding:
    dimension = 2
    model_name = "test-qasper-runner-embedding"

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _FakeReranker:
    def rerank(self, _query, candidates, *, top_k):
        return candidates[:top_k]


class _FakeAnswerer:
    provider = "fake"
    model = "test-answerer"

    def __call__(self, question, retrieval):
        assert retrieval.candidates
        assert all(
            item.chunk.document_id == f"qasper:validation:{question.paper_id}"
            for item in retrieval.candidates
        )
        return QasperGeneratedAnswer(
            answer=f"Evidence for {question.question_id}.",
            provider=self.provider,
            model=self.model,
            latency_ms=2.5,
            metadata={"verification_passed": True},
        )


class _UnusedTextService:
    provider_name = "fake"
    model = "must-not-be-called"


def _dataset(tmp_path):
    path = tmp_path / "runner-sample.json"
    path.write_text(
        json.dumps(
            {
                "paper-a": {
                    "title": "Evidence paper A",
                    "abstract": "Evidence for question A.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [
                                "Evidence for question A is in this paragraph."
                            ],
                        }
                    ],
                    "qas": [
                        {
                            "question_id": "q-a",
                            "question": "What supports answer A?",
                            "answers": [
                                {
                                    "annotation_id": "a-a",
                                    "answer": {"free_form_answer": "This paragraph."},
                                    "evidence": [
                                        "Evidence for question A is in this paragraph."
                                    ],
                                }
                            ],
                        }
                    ],
                },
                "paper-b": {
                    "title": "Evidence paper B",
                    "abstract": "Evidence for question B.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [
                                "Evidence for question B is in this paragraph."
                            ],
                        }
                    ],
                    "qas": [
                        {
                            "question_id": "q-b",
                            "question": "What supports answer B?",
                            "answers": [
                                {
                                    "annotation_id": "a-b",
                                    "answer": {"free_form_answer": "This paragraph."},
                                    "evidence": [
                                        "Evidence for question B is in this paragraph."
                                    ],
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return load_qasper(path)


def test_runner_scopes_each_question_and_writes_run_artifacts(tmp_path) -> None:
    embedding = _FakeEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(
            model=embedding.model_name,
            dimension=embedding.dimension,
        )
    )
    result = run_qasper_benchmark(
        _dataset(tmp_path),
        root=tmp_path / "benchmark",
        mode="full",
        config=config,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        answerer=_FakeAnswerer(),
        run_id="test-known-paper-run",
    )

    assert result.run_status == "complete"
    assert result.question_count == 2
    assert result.error_count == 0
    for output_path in (
        result.manifest_path,
        result.predictions_path,
        result.retrieval_trace_path,
        result.metrics_path,
        result.errors_path,
        result.qrels_path,
    ):
        assert output_path.exists()

    predictions = [
        json.loads(line)
        for line in result.predictions_path.read_text(encoding="utf-8").splitlines()
    ]
    traces = [
        json.loads(line)
        for line in result.retrieval_trace_path.read_text(encoding="utf-8").splitlines()
    ]
    qrels = [
        json.loads(line)
        for line in result.qrels_path.read_text(encoding="utf-8").splitlines()
    ]

    assert [item["question_id"] for item in predictions] == ["q-a", "q-b"]
    assert [item["answer"] for item in predictions] == [
        "Evidence for q-a.",
        "Evidence for q-b.",
    ]
    assert all(
        trace["scope_document_id"] == f"qasper:validation:{trace['paper_id']}"
        and all(
            candidate["document_id"] == trace["scope_document_id"]
            for candidate in trace["final_candidates"]
        )
        for trace in traces
    )
    assert all(trace["stages"]["pre_rerank_chunk_ids"] for trace in traces)
    assert all(qrel["expected_retrieval"] for qrel in qrels)
    assert all(qrel["gold_evidence_paragraph_ids"] for qrel in qrels)
    assert json.loads(result.metrics_path.read_text(encoding="utf-8"))["answer_count"] == 2


def test_question_sampling_is_reproducible_and_keeps_only_used_papers(tmp_path) -> None:
    dataset = _dataset(tmp_path)

    first = sample_qasper_dataset(dataset, limit=1, seed=42)
    second = sample_qasper_dataset(dataset, limit=1, seed=42)

    assert [item.question_id for item in first.questions] == [
        item.question_id for item in second.questions
    ]
    assert set(first.papers) == {first.questions[0].paper_id}
    assert first.papers[first.questions[0].paper_id].question_ids == (
        first.questions[0].question_id,
    )


def test_answerer_uses_qasper_abstention_when_retrieval_returns_no_evidence(
    tmp_path,
) -> None:
    question = _dataset(tmp_path).questions[0]
    answerer = GroundedQasperAnswerer(text_service=_UnusedTextService())

    answer = answerer(question, RetrievalResult(query=question.question))

    assert answer.answer == "Unanswerable"
    assert answer.metadata == {"abstained": True, "reason": "no_retrieved_evidence"}
