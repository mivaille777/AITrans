from __future__ import annotations

import json
from pathlib import Path

from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run
from backend.rag.benchmarks.qasper.loader import load_qasper
from backend.rag.benchmarks.qasper.runner import (
    GroundedQasperAnswerer,
    QasperGeneratedAnswer,
    run_qasper_ablation,
    run_qasper_adaptive_retrieval_ablation,
    run_qasper_benchmark,
    run_qasper_evidence_selection_ablation,
    run_qasper_raptor_ablation,
)
from backend.rag.benchmarks.qasper.sampling import sample_qasper_dataset
from backend.rag.config import RagConfig, RagEmbeddingConfig
from backend.rag.models import RetrievalResult
from backend.rag.query_planner import RagQueryPlan
from backend.rag.raptor import ExtractiveRaptorSummaryProvider


class _FakeEmbedding:
    dimension = 2
    model_name = "test-qasper-runner-embedding"

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _QasperEvidenceEmbedding(_FakeEmbedding):
    model_name = "test-qasper-evidence-selection-embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0]
            if any(term in text.casefold() for term in ("treatment", "outcome"))
            else [0.0, 1.0]
            for text in texts
        ]


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


class _EvidenceMetricsAnswerer(_FakeAnswerer):
    def __call__(self, question, retrieval):
        super().__call__(question, retrieval)
        return QasperGeneratedAnswer(
            answer=f"Grounded answer for {question.question_id}.",
            provider=self.provider,
            model=self.model,
            latency_ms=2.5,
            metadata={
                "verification_passed": True,
                "claim_count": 4,
                "unsupported_claim_count": 1,
            },
        )


class _FakeQueryPlanner:
    def plan(self, query):
        return RagQueryPlan(
            original_query=query,
            rewritten_query=query,
            subqueries=[f"{query} supporting evidence"],
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
                "paper-c": {
                    "title": "Unanswerable paper C",
                    "abstract": "Context for question C.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": ["The results do not address question C."],
                        }
                    ],
                    "qas": [
                        {
                            "question_id": "q-c",
                            "question": "Does the paper address question C?",
                            "answers": [
                                {
                                    "annotation_id": "a-c",
                                    "answer": {"unanswerable": True},
                                    "evidence": [],
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
    assert result.question_count == 3
    assert result.error_count == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["git_sha"] and manifest["git_sha"] != "unknown"
    assert manifest["dataset"] == "qasper"
    assert manifest["dataset_version"] == "0.3"
    assert manifest["split"] == "validation"
    assert manifest["seed"] == 42
    assert manifest["variant"]
    assert len(manifest["config_hash"]) == 64
    assert manifest["index_fingerprint"] == manifest["index"]["fingerprint"]
    assert manifest["embedding_model"] == manifest["embedding"]["model"]
    assert manifest["reranker_model"] == config.reranker.model
    assert manifest["hardware"]["python_version"]
    assert manifest["cache_hits"]["index"] is False
    assert manifest["cache_hits"]["indexed_paper_count"] == manifest["paper_count"]
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

    assert [item["question_id"] for item in predictions] == ["q-a", "q-b", "q-c"]
    assert [item["answer"] for item in predictions] == [
        "Evidence for q-a.",
        "Evidence for q-b.",
        "Evidence for q-c.",
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
    unanswerable_trace = next(trace for trace in traces if trace["question_id"] == "q-c")
    assert unanswerable_trace["final_candidates"]
    assert all(qrel["expected_retrieval"] for qrel in qrels)
    assert all(qrel["gold_evidence_paragraph_ids"] for qrel in qrels[:2])
    assert all("gold_evidence_section_indices" in qrel for qrel in qrels)
    assert qrels[2]["gold_evidence_paragraph_ids"] == []
    assert json.loads(result.metrics_path.read_text(encoding="utf-8"))["answer_count"] == 3

    for trace, latency in zip(traces, (1.0, 2.0, 100.0), strict=True):
        trace["latency_ms"] = latency
    result.retrieval_trace_path.write_text(
        "".join(json.dumps(trace, separators=(",", ":")) + "\n" for trace in traces),
        encoding="utf-8",
    )

    metrics = evaluate_qasper_run(result.run_directory, root=tmp_path / "benchmark")
    assert metrics["question_count"] == 3
    assert metrics["ai_trans_retrieval"]["evaluated_cases"] == 2
    assert metrics["performance_ms"]["total_rag_ms"]["samples"] == 3
    assert metrics["official_qasper"]["all_evidence"]["Missing predictions"] == 0
    assert 0 <= metrics["official_qasper"]["all_evidence"]["Answer F1"] <= 1
    assert 0 <= metrics["official_qasper"]["text_evidence_only"]["Evidence F1"] <= 1
    assert metrics["paragraph_evidence"]["evaluated_cases"] == 2
    assert metrics["paragraph_evidence"]["Gold Evidence Recall@20"] > 0
    assert json.loads(result.metrics_path.read_text(encoding="utf-8"))["metric_version"] == 4
    assert metrics["evidence_gate_evaluation"]["evaluated_decisions"] == 0
    assert metrics["evidence_gate_evaluation"]["excluded_no_gold_evidence_cases"] == 0
    assert all("official_answer_f1" in item for item in metrics["per_question"])
    assert all("official_evidence_f1" in item for item in metrics["per_question"])
    assert all(isinstance(item["error_types"], list) for item in metrics["per_question"])
    unanswerable_metrics = next(item for item in metrics["per_question"] if item["question_id"] == "q-c")
    assert "latency_outlier" in unanswerable_metrics["error_types"]
    assert set(metrics["error_taxonomy"]["counts"]) == {
        "retrieval_miss",
        "rerank_drop",
        "wrong_section",
        "evidence_incomplete",
        "premature_stop",
        "unnecessary_retrieval",
        "answer_unsupported",
        "unanswerable_failure",
        "latency_outlier",
    }


def test_gate_sufficiency_metrics_compare_predictions_with_qasper_gold() -> None:
    from backend.rag.benchmarks.qasper.evaluator import _binary_sufficiency_metrics

    metrics = _binary_sufficiency_metrics(
        predictions=[True, True, False, False],
        labels=[True, False, True, False],
    )

    assert metrics["true_positive"] == 1
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["true_negative"] == 1
    assert metrics["Sufficiency Precision"] == 0.5
    assert metrics["Sufficiency Recall"] == 0.5
    assert metrics["Sufficiency F1"] == 0.5


def test_qasper_error_taxonomy_identifies_retrieval_and_answer_failures() -> None:
    from backend.rag.benchmarks.qasper.evaluator import _classify_error_types

    qrel = {
        "no_answer": False,
        "answers": [{"evidence_paragraph_ids": ["gold-p1"]}],
        "gold_evidence_section_indices": [2],
    }
    prediction = {
        "answer": "unsupported answer",
        "answer_generation": {"metadata": {"unsupported_claim_count": 1}},
    }
    trace = {
        "pre_rerank_candidates": [{"source_paragraph_ids": ["gold-p1"]}],
        "final_candidates": [
            {"source_paragraph_ids": ["wrong-p1"], "source_section_indices": [5]}
        ],
        "retrieval_rounds": [
            {
                "candidate_chunk_ids": ["chunk-1"],
                "new_chunk_count": 1,
                "context_evidence_paragraph_ids": [],
                "gate": {"action": "stop"},
            },
            {
                "candidate_chunk_ids": ["chunk-1"],
                "new_chunk_count": 0,
                "context_evidence_paragraph_ids": [],
            },
        ],
    }

    errors = _classify_error_types(
        qrel,
        prediction,
        trace,
        {"gold_evidence_recall_at_10": 0.0, "evidence_f1_at_10": 0.0},
    )

    assert errors == [
        "retrieval_miss",
        "rerank_drop",
        "wrong_section",
        "premature_stop",
        "unnecessary_retrieval",
        "answer_unsupported",
    ]

    partial = _classify_error_types(
        {
            "no_answer": False,
            "answers": [{"evidence_paragraph_ids": ["p1", "p2"]}],
            "gold_evidence_section_indices": [2],
        },
        {},
        {"final_candidates": [{"source_paragraph_ids": ["p1"], "source_section_indices": [2]}]},
        {"gold_evidence_recall_at_10": 0.5, "evidence_f1_at_10": 0.5},
    )
    assert partial == ["evidence_incomplete"]

    unanswerable = _classify_error_types(
        {"no_answer": True, "answers": []},
        {"answer": "Yes", "answer_generation": {"provider": "test"}},
        {},
        {},
    )
    assert unanswerable == ["unanswerable_failure"]


def test_official_qasper_text_evidence_metric_excludes_float_evidence() -> None:
    from backend.rag.benchmarks.qasper.evaluator import _official_qasper_metrics

    qrels = [
        {
            "question_id": "q-float",
            "answers": [
                {
                    "answer": "Yes",
                    "answer_type": "boolean",
                    "evidence_texts": ["text paragraph", "FLOAT SELECTED Figure 1"],
                }
            ],
        }
    ]
    predictions = [
        {
            "question_id": "q-float",
            "answer": "Yes",
            "predicted_evidence": ["text paragraph"],
        }
    ]

    full = _official_qasper_metrics(qrels, predictions, text_evidence_only=False)
    text_only = _official_qasper_metrics(qrels, predictions, text_evidence_only=True)

    assert full["Evidence F1"] < text_only["Evidence F1"]
    assert text_only["Evidence F1"] == 1.0


def test_ablation_suite_reuses_one_index_and_records_variant_metrics(tmp_path) -> None:
    embedding = _FakeEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(
            model=embedding.model_name,
            dimension=embedding.dimension,
        )
    )
    variants = ("B0", "B1", "B5", "B7", "FULL")
    result = run_qasper_ablation(
        _dataset(tmp_path),
        root=tmp_path / "ablation",
        mode="full",
        config=config,
        variants=variants,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        answerer=_FakeAnswerer(),
        query_planner=_FakeQueryPlanner(),
        suite_id="test-qasper-ablation",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    rows = {row["variant_id"]: row for row in comparison["variants"]}

    assert result.status == "complete"
    assert result.variant_count == len(variants)
    assert [item["variant_id"] for item in manifest["completed_runs"]] == list(variants)
    assert manifest["index_rebuild"] is False
    assert manifest["completed_runs"][0]["index_cache_hit"] is False
    assert all(item["index_cache_hit"] for item in manifest["completed_runs"][1:])
    assert rows["B5"]["context_metrics"]["Context Tokens"] > 0
    assert rows["B7"]["adaptive_retrieval"]["gate_observed_cases"] == 3
    assert rows["B7"]["evidence_gate_evaluation"]["evaluated_question_count"] == 2
    assert rows["B7"]["evidence_gate_evaluation"]["excluded_no_gold_evidence_cases"] == 1
    assert rows["B7"]["evidence_gate_evaluation"]["evaluated_decisions"] > 0

    b0_trace = rows["B0"]["run_directory"]
    b0_trace_path = tmp_path / "ablation" / "results"
    b0_run_dir = tmp_path / "ablation" / "results" / Path(b0_trace).name
    trace = json.loads(
        (b0_run_dir / "retrieval_trace.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert trace["ablation_variant"]["variant_id"] == "B0"
    assert trace["retrieval_metadata"]["dense_enabled"] is True
    assert trace["retrieval_metadata"]["sparse_enabled"] is False
    assert b0_trace_path.exists()


def test_raptor_suite_caches_trees_and_groups_results_by_evidence_scope(tmp_path) -> None:
    embedding = _FakeEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(
            model=embedding.model_name,
            dimension=embedding.dimension,
        )
    )
    result = run_qasper_raptor_ablation(
        _dataset(tmp_path),
        root=tmp_path / "raptor-ablation",
        mode="full",
        config=config,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        summary_provider=ExtractiveRaptorSummaryProvider(),
        answerer=_FakeAnswerer(),
        suite_id="test-qasper-raptor-ablation",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    rows = {row["variant_id"]: row for row in comparison["variants"]}

    assert result.status == "complete"
    assert result.variant_count == 4
    assert result.tree_count == 3
    assert manifest["tree_cache_parameters"]["query_parameters_included"] is False
    assert all(not item["cache_hit"] for item in manifest["trees"].values())
    assert all(item["index_cache_hit"] for item in manifest["completed_runs"])
    assert rows["R1"]["raptor_category_metrics"]["Local"]["question_count"] == 2
    assert rows["R2"]["raptor_category_metrics"]["Overall"]["question_count"] == 3
    assert rows["R3"]["raptor_category_metrics"]["unanswerable_question_count"] == 1

    r2_directory = Path(rows["R2"]["run_directory"])
    trace = json.loads(
        (r2_directory / "retrieval_trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert trace["raptor_variant"] == "R2"
    assert trace["raptor_category"] == "local"
    assert trace["retrieval_metadata"]["raptor_variant"] == "R2"
    assert trace["retrieval_metadata"]["raptor_summary_hits"]
    assert trace["final_candidates"]


def test_qasper_evidence_selection_suite(tmp_path) -> None:
    paragraph = (
        "Evidence for question A supports the treatment outcome. "
        "Separate historical context describes earlier work. "
        "Methods include a laboratory preparation detail. "
        "Another background detail appears in the introduction. "
        "A fifth unrelated sentence names a general condition. "
        "A sixth statement covers a different topic. "
        "A seventh unrelated result is summarized. "
        "An eighth sentence adds extra discussion."
    )
    path = tmp_path / "evidence-selection-sample.json"
    path.write_text(
        json.dumps(
            {
                "paper-a": {
                    "title": "Evidence selection paper",
                    "abstract": "A small fixture for this article.",
                    "full_text": [
                        {"section_name": "Results", "paragraphs": [paragraph]}
                    ],
                    "qas": [
                        {
                            "question_id": "q-a",
                            "question": "What evidence supports the treatment outcome?",
                            "answers": [
                                {
                                    "annotation_id": "a-a",
                                    "answer": {
                                        "free_form_answer": "The treatment outcome."
                                    },
                                    "evidence": [paragraph],
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    dataset = load_qasper(path)
    embedding = _QasperEvidenceEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(
            model=embedding.model_name,
            dimension=embedding.dimension,
        )
    )
    result = run_qasper_evidence_selection_ablation(
        dataset,
        root=tmp_path / "es",
        mode="full",
        config=config,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        answerer=_EvidenceMetricsAnswerer(),
        suite_id="test-evidence-selection",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    rows = {row["variant_id"]: row for row in comparison["variants"]}

    assert result.status == "complete"
    assert result.variant_count == 3
    assert manifest["index_rebuild"] is False
    assert manifest["completed_runs"][0]["index_cache_hit"] is False
    assert all(run["index_cache_hit"] for run in manifest["completed_runs"][1:])
    raw_tokens = rows["raw_top_k"]["context_metrics"]["Context Tokens"]
    selected_tokens = rows["evidence_selection"]["context_metrics"]["Context Tokens"]
    assert selected_tokens < raw_tokens
    assert rows["evidence_selection"]["groundedness_metrics"][
        "Unsupported Claim Rate"
    ] == 0.25
    assert rows["evidence_selection"]["paragraph_evidence"][
        "Evidence F1@5"
    ] > 0
    assert rows["evidence_selection"]["official_qasper"]["all_evidence"][
        "Answer F1"
    ] >= 0

    run_directory = Path(rows["evidence_selection"]["run_directory"])
    trace = json.loads(
        (run_directory / "retrieval_trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    selected_trace = trace["retrieval_metadata"]["evidence_selection"]
    assert trace["evidence_selection_variant"] == "evidence_selection"
    assert 1 <= selected_trace["candidate_pool_count"] <= 20
    assert selected_trace["selected_span_count"] == 1
    assert trace["retrieval_metadata"]["evidence_extraction_ms"] >= 0
    paragraph_candidates = [
        candidate
        for candidate in trace["final_candidates"]
        if candidate["source_paragraph_ids"]
    ]
    assert paragraph_candidates
    assert all(candidate["text"] in paragraph for candidate in paragraph_candidates)


def test_qasper_adaptive_retrieval_suite_tracks_missing_requirements(tmp_path) -> None:
    path = tmp_path / "adaptive-retrieval-sample.json"
    path.write_text(
        json.dumps(
            {
                "paper-a": {
                    "title": "Adaptive retrieval paper",
                    "abstract": "A short abstract for the fixture.",
                    "full_text": [
                        {
                            "section_name": "Discussion",
                            "paragraphs": [
                                "This passage provides a brief scientific description."
                            ],
                        }
                    ],
                    "qas": [
                        {
                            "question_id": "q-adaptive",
                            "question": "How does the method improve accuracy on the dataset?",
                            "answers": [
                                {
                                    "annotation_id": "a-adaptive",
                                    "answer": {
                                        "free_form_answer": "The question is not addressed."
                                    },
                                    "evidence": [
                                        "This passage provides a brief scientific description."
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    dataset = load_qasper(path)
    embedding = _FakeEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(
            model=embedding.model_name,
            dimension=embedding.dimension,
        )
    )
    result = run_qasper_adaptive_retrieval_ablation(
        dataset,
        root=tmp_path / "adaptive",
        mode="full",
        config=config,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        answerer=_FakeAnswerer(),
        query_planner=_FakeQueryPlanner(),
        suite_id="test-adaptive-retrieval",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    rows = {row["variant_id"]: row for row in comparison["variants"]}
    requirement_metrics = rows["requirement_aware"][
        "evidence_requirement_evaluation"
    ]

    assert result.status == "complete"
    assert result.variant_count == 4
    assert manifest["completed_runs"][0]["index_cache_hit"] is False
    assert all(run["index_cache_hit"] for run in manifest["completed_runs"][1:])
    assert requirement_metrics["evaluated_questions"] == 1
    assert requirement_metrics["requirement_count"] == 3
    assert requirement_metrics["covered_requirement_count"] == 0
    assert requirement_metrics["Re-retrieval Case Rate"] == 1.0
    assert requirement_metrics["Mean Retrieval Rounds"] == 3.0

    run_directory = Path(rows["requirement_aware"]["run_directory"])
    trace = json.loads(
        (run_directory / "retrieval_trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert trace["adaptive_variant"] == "requirement_aware"
    assert trace["second_round"] is True
    assert len(trace["retrieval_rounds"]) == 3
    assert {item["type"] for item in trace["evidence_requirements"]} == {
        "method",
        "result",
        "data",
    }
    assert all(item["status"] == "missing" for item in trace["evidence_requirements"])


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
