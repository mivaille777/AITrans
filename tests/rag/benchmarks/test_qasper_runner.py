from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.benchmarks.qasper.ablation import DEFAULT_QASPER_VARIANT
from backend.rag.benchmarks.qasper.answer_contract import QasperContractAnswer
from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run
from backend.rag.benchmarks.qasper.loader import load_qasper
from backend.rag.benchmarks.qasper.runner import (
    DEFAULT_EVIDENCE_SELECTION_PROFILE,
    GroundedQasperAnswerer,
    QasperAnswerInput,
    QasperGeneratedAnswer,
    _profile_sha256,
    _requirement_query_expansion,
    _reranked_candidate_pool,
    _retrieve_raptor_question,
    _retrieve_requirement_aware_question,
    _retrieve_variant_question,
    _verify_direct_contract_answer,
    run_qasper_ablation,
    run_qasper_adaptive_retrieval_ablation,
    run_qasper_benchmark,
    run_qasper_evidence_selection_ablation,
    run_qasper_raptor_ablation,
)
from backend.rag.benchmarks.qasper.sampling import sample_qasper_dataset
from backend.rag.config import RagConfig, RagEmbeddingConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import RagQueryPlan
from backend.rag.raptor import ExtractiveRaptorSummaryProvider, RaptorTree
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier


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
    prompt_id = "fake-answerer-v1"

    def __call__(self, question, retrieval):
        assert not hasattr(question, "answers")
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
                "initial_claim_count": 6,
                "initial_unsupported_claim_count": 3,
                "repair_claim_count": 3,
                "repair_unsupported_claim_count": 1,
                "claim_repair_attempted": True,
                "claim_repair_succeeded": True,
            },
        )


class _FakeQueryPlanner:
    def plan(self, query):
        return RagQueryPlan(
            original_query=query,
            rewritten_query=query,
            subqueries=[f"{query} supporting evidence"],
        )


class _RelevantRequirementQueryPlanner:
    def plan(self, query):
        return RagQueryPlan(
            original_query=query,
            rewritten_query="dataset sample participants evidence",
            subqueries=[],
        )


class _SequentialRetrievalService:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []

    def retrieve(self, query, **_kwargs):
        self.queries.append(query)
        return self.results.pop(0)


class _FinalTopKRecordingRetrievalService:
    def __init__(self, result):
        self.result = result
        self.final_top_ks = []

    def retrieve(self, query, **kwargs):
        self.final_top_ks.append(kwargs["final_top_k"])
        return self.result.model_copy(update={"query": query})


class _ChunkLookup:
    def __init__(self, chunks):
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id):
        return self.chunks.get(chunk_id)


def _retrieval_result(chunk_id, text, *, document_id="paper-doc", paragraph_id=None):
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        chunk_index=0,
        metadata=(
            {"source_paragraph_ids": [paragraph_id]}
            if paragraph_id is not None
            else {}
        ),
    )
    return RetrievalResult(
        query="fixture query",
        candidates=[RetrievalCandidate(chunk=chunk, rank=1)],
        retrieval_strategy="fixture",
    )
class _UnusedTextService:
    provider_name = "fake"
    model = "must-not-be-called"


class _FakeCompletionClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.outputs.pop(0)


class _FakeTextService:
    provider_name = "fixture"
    model = "fixture-answer-model"

    def __init__(self, outputs):
        self.provider = SimpleNamespace(client=_FakeCompletionClient(outputs))


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


def test_profile_sha256_is_stable_and_content_sensitive(tmp_path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text('{"final_top_k": 8}\n', encoding="utf-8")
    first = _profile_sha256(profile)
    second = _profile_sha256(profile)
    assert first == second
    assert len(first) == 64

    profile.write_text('{"final_top_k": 9}\n', encoding="utf-8")
    assert _profile_sha256(profile) != first


def test_qasper_retrieval_uses_configured_final_top_k() -> None:
    document_id = "qasper:validation:paper-a"
    retrieval_service = _FinalTopKRecordingRetrievalService(
        _retrieval_result(
            "chunk-a",
            "Evidence for question A.",
            document_id=document_id,
        )
    )
    index = SimpleNamespace(
        runtime=SimpleNamespace(
            config=SimpleNamespace(
                retrieval=SimpleNamespace(final_top_k=8),
            ),
            retrieval_service=retrieval_service,
        )
    )

    _retrieve_variant_question(
        SimpleNamespace(question="What supports the answer?"),
        index=index,
        document_id=document_id,
        variant=DEFAULT_QASPER_VARIANT,
        query_planner=None,
    )

    assert retrieval_service.final_top_ks == [8]


def test_reranked_candidate_pool_keeps_candidates_above_final_top_k() -> None:
    document_id = "qasper:validation:paper-a"
    chunks = [
        DocumentChunk(
            chunk_id=f"chunk-{index}",
            document_id=document_id,
            text=f"Evidence paragraph {index}.",
            chunk_index=index,
            metadata={"source_paragraph_ids": [f"p{index}"]},
        )
        for index in range(5)
    ]
    retrieval = RetrievalResult(
        query="question",
        candidates=[RetrievalCandidate(chunk=chunks[0], rank=1)],
        metadata={"post_rerank_chunk_ids": [chunk.chunk_id for chunk in chunks]},
    )
    index = SimpleNamespace(
        runtime=SimpleNamespace(sparse_retriever=_ChunkLookup(chunks))
    )

    pool = _reranked_candidate_pool(
        index=index,
        retrieval=retrieval,
        scope_document_id=document_id,
    )

    assert [item.chunk.chunk_id for item in pool] == [
        chunk.chunk_id for chunk in chunks
    ]
    assert [item.rank for item in pool] == [1, 2, 3, 4, 5]


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
        config_profile_id="test-profile-v1",
        config_profile_sha256="a" * 64,
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
    assert manifest["config_profile_id"] == "test-profile-v1"
    assert manifest["config_profile_sha256"] == "a" * 64
    assert manifest["prompt_id"] == "fake-answerer-v1"
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

    complete_with_extra_evidence = _classify_error_types(
        {
            "no_answer": False,
            "answers": [{"evidence_paragraph_ids": ["p1"]}],
            "gold_evidence_section_indices": [2],
        },
        {},
        {
            "final_candidates": [
                {"source_paragraph_ids": ["p1", "extra-p1"], "source_section_indices": [2]}
            ]
        },
        {"gold_evidence_recall_at_10": 1.0, "evidence_f1_at_10": 0.5},
    )
    assert complete_with_extra_evidence == []

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
    assert rows["R0"]["run_status"] == "complete"
    assert rows["R0"]["error_count"] == 0
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


def test_raptor_suite_applies_fixed_evidence_selection_profile(tmp_path) -> None:
    embedding = _FakeEmbedding()
    result = run_qasper_raptor_ablation(
        _dataset(tmp_path),
        root=tmp_path / "raptor-selected",
        mode="full",
        config=RagConfig(
            embedding=RagEmbeddingConfig(
                model=embedding.model_name,
                dimension=embedding.dimension,
            )
        ),
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        summary_provider=ExtractiveRaptorSummaryProvider(),
        answerer=_FakeAnswerer(),
        variants=("R0", "R3"),
        suite_id="test-qasper-raptor-selected",
        evidence_selection_variant="evidence_selection",
        quality_profile=DEFAULT_EVIDENCE_SELECTION_PROFILE,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    assert result.status == "complete"
    assert manifest["evidence_selection_variant"] == "evidence_selection"
    assert manifest["quality_profile_sha256"]
    for row in comparison["variants"]:
        trace = json.loads(
            (Path(row["run_directory"]) / "retrieval_trace.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert trace["evidence_selection_variant"] == "evidence_selection"
        assert trace["raptor_variant"] in {"R0", "R3"}
        assert trace["selected_evidence"]
        assert trace["retrieval_metadata"]["evidence_selection"]


def test_raptor_empty_summary_candidates_fall_back_to_scoped_flat_retrieval(
    tmp_path,
) -> None:
    chunk = DocumentChunk(
        chunk_id="paper-leaf",
        document_id="paper-1",
        text="A directly relevant result.",
        title="Paper",
        section_heading="Results",
        chunk_index=0,
        token_count=5,
    )
    calls: list[object] = []

    def retrieve(_query, *, filters, **_kwargs):
        calls.append(filters.document_ids)
        return RetrievalResult(
            query="question",
            candidates=[RetrievalCandidate(chunk=chunk, rank=1)],
            retrieval_strategy="hybrid",
            elapsed_ms=1.0,
            metadata={
                "dense_count": 1,
                "sparse_count": 1,
                "reranker_applied": True,
            },
        )

    index = SimpleNamespace(
        runtime=SimpleNamespace(
            embedding_provider=_FakeEmbedding(),
            sparse_retriever=SimpleNamespace(get_chunk=lambda _id: chunk),
            retrieval_service=SimpleNamespace(retrieve=retrieve),
        )
    )
    tree = RaptorTree(
        document_id="paper-1",
        fingerprint="empty-tree",
        leaf_fingerprint="leaf",
        root_node_ids=(),
        nodes=(),
        cache_path=tmp_path / "empty.json",
        cache_hit=False,
        summary_calls=0,
        created_at="",
    )

    result, trace = _retrieve_raptor_question(
        "question",
        index=index,
        document_id="paper-1",
        tree=tree,
        variant="R2",
    )

    assert [item.chunk.chunk_id for item in result.candidates] == ["paper-leaf"]
    assert calls == [["paper-1"]]
    assert result.metadata["raptor_variant"] == "R2"
    assert result.metadata["raptor_fallback_reason"] == "empty_summary_candidates"
    assert trace["raptor_fallback_reason"] == "empty_summary_candidates"


def test_raptor_suite_reports_partial_when_a_variant_has_query_errors(
    tmp_path, monkeypatch
) -> None:
    import backend.rag.benchmarks.qasper.runner as qasper_runner

    def failing_retrieval(*_args, **_kwargs):
        raise RuntimeError("simulated retrieval failure")

    monkeypatch.setattr(qasper_runner, "_retrieve_raptor_question", failing_retrieval)
    embedding = _FakeEmbedding()
    result = run_qasper_raptor_ablation(
        _dataset(tmp_path),
        root=tmp_path / "raptor-partial",
        mode="full",
        config=RagConfig(
            embedding=RagEmbeddingConfig(
                model=embedding.model_name,
                dimension=embedding.dimension,
            )
        ),
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        summary_provider=ExtractiveRaptorSummaryProvider(),
        variants=("R0",),
        suite_id="test-qasper-raptor-partial",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    assert result.status == manifest["status"] == "partial"
    assert comparison["variants"][0]["run_status"] == "partial"
    assert comparison["variants"][0]["error_count"] == 3


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
    assert result.variant_count == 5
    assert manifest["index_rebuild"] is False
    assert manifest["completed_runs"][0]["index_cache_hit"] is False
    assert all(run["index_cache_hit"] for run in manifest["completed_runs"][1:])
    assert manifest["quality_profile"]["profile_id"] == "p1q1-evidence-selection-v2"
    assert rows["rerank_top5"]["run_status"] == "complete"
    current_tokens = rows["current_top20"]["context_metrics"]["Context Tokens"]
    selected_tokens = rows["evidence_selection"]["context_metrics"]["Context Tokens"]
    assert selected_tokens < current_tokens
    assert rows["evidence_selection"]["groundedness_metrics"][
        "Unsupported Claim Rate"
    ] == 0.25
    assert rows["evidence_selection"]["groundedness_metrics"][
        "Initial Unsupported Claim Rate"
    ] == 0.5
    assert rows["evidence_selection"]["groundedness_metrics"][
        "Repair Unsupported Claim Rate"
    ] == (1 / 3)
    assert rows["evidence_selection"]["groundedness_metrics"][
        "claim_repair_attempts"
    ] == 1
    assert rows["evidence_selection"]["groundedness_metrics"][
        "claim_repair_successes"
    ] == 1
    assert rows["evidence_selection"]["paragraph_evidence"][
        "Evidence F1@5"
    ] > 0
    assert "Evidence F1@8" in rows["rerank_top8"]["paragraph_evidence"]
    assert rows["current_top20"]["candidate_pool_evidence"][
        "Gold Evidence Recall@5"
    ] >= rows["evidence_selection"]["paragraph_evidence"][
        "Gold Evidence Recall@5"
    ]
    assert rows["evidence_selection"]["answerer_invocations"] == 1
    assert rows["evidence_selection"]["estimated_llm_invocations"] == 1
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
    assert trace["retrieval_candidate_pool"]
    assert len(trace["selected_evidence"]) == selected_trace[
        "final_selected_evidence_count"
    ]
    assert len(trace["selected_evidence"]) <= 5
    paragraph_candidates = [
        candidate
        for candidate in trace["final_candidates"]
        if candidate["source_paragraph_ids"]
    ]
    assert paragraph_candidates
    excerpt_candidates = []
    for candidate in paragraph_candidates:
        selection = candidate["metadata"]["evidence_selection"]
        pool_candidate = next(
            item
            for item in trace["retrieval_candidate_pool"]
            if item["chunk_id"] == selection["source_chunk_id"]
        )
        if selection.get("fallback_applied"):
            assert candidate["text"] == pool_candidate["text"]
        else:
            assert candidate["text"] in paragraph
            excerpt_candidates.append(candidate)
    assert excerpt_candidates
    selected_candidate = excerpt_candidates[0]
    selection = selected_candidate["metadata"]["evidence_selection"]
    pool_candidate = next(
        candidate
        for candidate in trace["retrieval_candidate_pool"]
        if candidate["chunk_id"] == selection["source_chunk_id"]
    )
    assert pool_candidate["text"][selection["start_offset"] : selection["end_offset"]] == (
        selected_candidate["text"]
    )
    prediction = json.loads(
        (run_directory / "predictions.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert prediction["predicted_evidence_paragraph_ids"] == trace[
        "selected_evidence_paragraph_ids"
    ]
    assert prediction["retrieved_chunk_ids"] == [
        candidate["chunk_id"] for candidate in trace["retrieval_candidate_pool"]
    ]


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
    assert requirement_metrics["Mean Retrieval Rounds"] == 2.0

    run_directory = Path(rows["requirement_aware"]["run_directory"])
    trace = json.loads(
        (run_directory / "retrieval_trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert trace["adaptive_variant"] == "requirement_aware"
    assert trace["second_round"] is True
    assert len(trace["retrieval_rounds"]) == 2
    assert trace["retrieval_stop_reason"] == "no_novel_evidence"
    assert trace["retrieval_rounds"][0]["gate"]["action"] == "retrieve"
    assert trace["retrieval_rounds"][0]["next_query"]
    assert trace["retrieval_rounds"][1]["gate"]["action"] == "stop"
    assert trace["retrieval_rounds"][1]["gate"]["reason_codes"] == [
        "no_novel_evidence"
    ]
    assert trace["retrieval_rounds"][1]["gate"]["sufficient"] is False
    assert trace["retrieval_rounds"][1]["evidence_requirements"][0]["status"] == (
        "missing"
    )
    assert {item["type"] for item in trace["evidence_requirements"]} == {
        "method",
        "result",
        "data",
    }
    assert all(item["status"] == "missing" for item in trace["evidence_requirements"])


def test_requirement_aware_second_round_adds_novel_evidence_and_stops_when_covered():
    retrieval_service = _SequentialRetrievalService(
        [
            _retrieval_result(
                "chunk-method-result",
                "The method uses a technique and improves accuracy results.",
                paragraph_id="p-method",
            ),
            _retrieval_result(
                "chunk-data",
                "The dataset contains participant samples; results report accuracy.",
                paragraph_id="p-data",
            ),
        ]
    )
    index = SimpleNamespace(
        runtime=SimpleNamespace(retrieval_service=retrieval_service)
    )
    question = SimpleNamespace(
        question="How does the method improve accuracy on the dataset?"
    )

    result, rounds, requirements, planning_ms, planner_calls, stop_reason = (
        _retrieve_requirement_aware_question(
            question,
            index=index,
            document_id="paper-doc",
            query_planner=_RelevantRequirementQueryPlanner(),
        )
    )

    assert len(retrieval_service.queries) == 2
    assert retrieval_service.queries[0] != retrieval_service.queries[1]
    assert len(rounds) == 2
    assert rounds[1]["novel_chunk_ids"] == ["chunk-data"]
    assert rounds[1]["gate"]["action"] == "stop"
    assert rounds[1]["gate"]["sufficient"] is True
    assert stop_reason == "evidence_requirements_covered"
    assert all(item.status == "covered" for item in requirements)
    assert result.metadata["requirement_round_count"] == 2
    assert result.metadata["query_planner_invocation_count"] == 1
    assert rounds[0]["query_plan_invocation_count"] == 1
    assert rounds[1]["query_planner_invoked"] is True
    assert planning_ms >= 0
    assert planner_calls == 1


def test_requirement_gate_uses_selected_top_k_not_the_full_candidate_pool():
    method_result = _retrieval_result(
        "chunk-method-result",
        "The method uses a technique and improves accuracy results.",
    ).candidates[0]
    data = _retrieval_result(
        "chunk-data",
        "The dataset contains samples from participants in a corpus.",
    ).candidates[0]
    retrieval_service = _SequentialRetrievalService(
        [
            RetrievalResult(
                query="fixture query",
                candidates=[method_result, data],
                retrieval_strategy="fixture",
            )
        ]
    )
    index = SimpleNamespace(
        runtime=SimpleNamespace(retrieval_service=retrieval_service)
    )
    question = SimpleNamespace(
        question="How does the method improve accuracy on the dataset?"
    )

    _result, rounds, requirements, _planning_ms, _planner_calls, _stop_reason = (
        _retrieve_requirement_aware_question(
            question,
            index=index,
            document_id="paper-doc",
            maximum_rounds=1,
            candidate_pool_size=20,
            gate_top_k=1,
        )
    )

    assert rounds[0]["gate_top_k"] == 1
    assert rounds[0]["gate_candidate_chunk_ids"] == ["chunk-method-result"]
    assert "chunk-data" not in rounds[0]["gate_candidate_chunk_ids"]
    assert any(item.type == "data" and item.status == "missing" for item in requirements)


def test_adaptive_retrieval_applies_q1q1_selection_and_keeps_round_traces(tmp_path):
    dataset = _dataset(tmp_path)
    embedding = _FakeEmbedding()
    config = RagConfig(
        embedding=RagEmbeddingConfig(
            model=embedding.model_name,
            dimension=embedding.dimension,
        )
    )
    result = run_qasper_adaptive_retrieval_ablation(
        dataset,
        root=tmp_path / "adaptive-selected",
        mode="full",
        config=config,
        embedding_provider=embedding,
        reranker=_FakeReranker(),
        answerer=_FakeAnswerer(),
        query_planner=_FakeQueryPlanner(),
        variants=("one_shot", "requirement_aware"),
        suite_id="test-adaptive-selected-evidence",
        evidence_selection_variant="evidence_selection",
        quality_profile=DEFAULT_EVIDENCE_SELECTION_PROFILE,
    )

    comparison = json.loads(result.comparison_path.read_text(encoding="utf-8"))
    rows = {row["variant_id"]: row for row in comparison["variants"]}
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    requirement_run = Path(rows["requirement_aware"]["run_directory"])
    trace = json.loads(
        (requirement_run / "retrieval_trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )

    assert result.status == "complete"
    assert manifest["evidence_selection_variant"] == "evidence_selection"
    assert manifest["quality_profile_sha256"]
    assert trace["adaptive_variant"] == "requirement_aware"
    assert trace["evidence_selection_variant"] == "evidence_selection"
    assert trace["retrieval_rounds"]
    assert trace["retrieval_candidate_pool"]
    assert 1 <= len(trace["final_candidates"]) <= 5
    assert trace["retrieval_rounds"][-1]["final_evidence_selection"]
    assert trace["retrieval_rounds"][-1]["final_selected_evidence_chunk_ids"] == [
        candidate["chunk_id"] for candidate in trace["final_candidates"]
    ]


def test_requirement_query_expansion_uses_question_specific_terms():
    assert "morphology" in _requirement_query_expansion(
        "What type of inflections are considered?",
        "answer",
    )
    detection_expansion = _requirement_query_expansion(
        "Do they build a model to automatically detect dimensions?",
        "answer",
    )
    assert "classification" in detection_expansion
    assert "demographic" in detection_expansion


def test_requirement_aware_retrieval_never_exceeds_three_rounds():
    retrieval_service = _SequentialRetrievalService(
        [
            _retrieval_result(f"chunk-{index}", f"generic passage number {index}")
            for index in range(3)
        ]
    )

    class _DistinctQueryPlanner:
        def __init__(self):
            self.calls = 0

        def plan(self, query):
            self.calls += 1
            return RagQueryPlan(
                original_query=query,
                rewritten_query=f"distinct evidence query {self.calls}",
                subqueries=[],
            )

    planner = _DistinctQueryPlanner()
    index = SimpleNamespace(
        runtime=SimpleNamespace(retrieval_service=retrieval_service)
    )
    question = SimpleNamespace(
        question="How does the method improve accuracy on the dataset?"
    )

    result, rounds, _requirements, _planning_ms, planner_calls, stop_reason = (
        _retrieve_requirement_aware_question(
            question,
            index=index,
            document_id="paper-doc",
            query_planner=planner,
            maximum_rounds=9,
        )
    )

    assert len(retrieval_service.queries) == 3
    assert len(set(retrieval_service.queries)) == 3
    assert len(rounds) == 3
    assert rounds[-1]["gate"]["reason_codes"] == ["retrieval_budget_exhausted"]
    assert stop_reason == "retrieval_budget_exhausted"
    assert result.metadata["requirement_round_count"] == 3
    assert planner.calls == planner_calls == 2


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
    assert answer.metadata == {
        "abstained": True,
        "reason": "no_retrieved_evidence",
        "answer_llm_invocation_count": 0,
    }


def test_qasper_answerer_repairs_unsupported_claim_and_records_serializable_trace():
    evidence_text = (
        "The method improves sample efficiency by using a surrogate model."
    )
    text_service = _FakeTextService(
        [
            "The method doubles success on every dataset [1].",
            f"{evidence_text} [1]",
        ]
    )
    answerer = GroundedQasperAnswerer(text_service=text_service)

    generated = answerer(
        QasperAnswerInput(
            question_id="question-a",
            paper_id="paper-a",
            question="How does the method improve sample efficiency?",
        ),
        _retrieval_result("chunk-evidence", evidence_text),
    )

    assert generated.answer == f"{evidence_text} [1]"
    assert generated.metadata["claim_repair_attempted"] is True
    assert generated.metadata["claim_repair_succeeded"] is True
    assert generated.metadata["repair_claim_count"] > 0
    assert generated.metadata["answer_llm_invocation_count"] == 2
    assert generated.metadata["initial_unsupported_claim_count"] > 0
    assert generated.metadata["repair_unsupported_claim_count"] == 0
    assert generated.metadata["raw_model_output"] == (
        "The method doubles success on every dataset [1]."
    )
    assert generated.metadata["repair_model_output"] == f"{evidence_text} [1]"
    json.dumps(generated.metadata, ensure_ascii=False)


def test_qasper_answerer_abstains_when_claim_repair_still_fails():
    evidence_text = (
        "The method improves sample efficiency by using a surrogate model."
    )
    answerer = GroundedQasperAnswerer(
        text_service=_FakeTextService(
            [
                "The method doubles success on every dataset [1].",
                "The method doubles success on every dataset [9].",
            ]
        )
    )

    generated = answerer(
        QasperAnswerInput(
            question_id="question-b",
            paper_id="paper-b",
            question="How does the method improve sample efficiency?",
        ),
        _retrieval_result("chunk-evidence", evidence_text),
    )

    assert generated.answer == "Unanswerable"
    assert generated.user_visible_answer == "Unanswerable"
    assert generated.metadata["abstained"] is True
    assert generated.metadata["abstention_reason"] == (
        "claim_repair_verification_failed"
    )
    assert generated.metadata["repair_claim_count"] > 0
    assert generated.metadata["repair_model_output"].endswith("[9].")


def test_contract_answer_only_recovery_keeps_only_strictly_supported_short_answer():
    evidence = [
        AgentEvidenceItem(
            evidence_id="evidence-supported",
            excerpt="The system uses a DNN-based acoustic model with 11 hidden layers.",
        ),
        AgentEvidenceItem(
            evidence_id="evidence-unrelated",
            excerpt="The dataset contains news articles about local sports.",
        ),
    ]
    citations = [
        AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence-supported"],
            label="[1]",
        ),
        AgentCitationRef(
            citation_id="citation-2",
            evidence_ids=["evidence-unrelated"],
            label="[2]",
        ),
    ]
    candidate = QasperContractAnswer(
        answer="The system uses a DNN-based acoustic model with 11 hidden layers.",
        answer_type="short",
        citations=("[1]", "[2]"),
        supporting_explanation="The method also improves every dataset.",
    )

    recovered = _verify_direct_contract_answer(
        candidate,
        verifier=AgentClaimEvidenceVerifier(),
        evidence=evidence,
        citations=citations,
    )

    assert recovered is not None
    recovered_answer, verification = recovered
    assert recovered_answer.citations == ("[1]",)
    assert recovered_answer.supporting_explanation == ""
    assert verification.strict_passed is True
    assert verification.claim_count == 1


def test_contract_answer_only_recovery_rejects_boolean_and_unsupported_answers():
    evidence = [
        AgentEvidenceItem(
            evidence_id="evidence-1",
            excerpt="The system uses a DNN-based acoustic model with 11 hidden layers.",
        )
    ]
    citations = [
        AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence-1"],
            label="[1]",
        )
    ]
    verifier = AgentClaimEvidenceVerifier()

    boolean = _verify_direct_contract_answer(
        QasperContractAnswer(
            answer="No",
            answer_type="boolean",
            citations=("[1]",),
            supporting_explanation="The method uses a DNN acoustic model.",
        ),
        verifier=verifier,
        evidence=evidence,
        citations=citations,
    )
    unsupported = _verify_direct_contract_answer(
        QasperContractAnswer(
            answer="A transformer model uses attention over image patches.",
            answer_type="short",
            citations=("[1]",),
            supporting_explanation="The method uses a DNN acoustic model.",
        ),
        verifier=verifier,
        evidence=evidence,
        citations=citations,
    )

    assert boolean is None
    assert unsupported is None
