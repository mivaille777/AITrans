from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.models.rag_debug import QasperDebugCompareRequest, QasperDebugRunRequest
from backend.rag.config import RagConfig
from backend.services import qasper_debug_service as service


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_qasper_debug_case_exposes_gold_mapping_and_official_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = tmp_path / "qasper"
    run_id = "debug-qasper-validation-test"
    run_dir = benchmark / "results" / run_id
    run_dir.mkdir(parents=True)
    qrels_path = benchmark / "qrels.jsonl"
    _write_jsonl(
        qrels_path,
        [
            {
                "question_id": "question-1",
                "paper_id": "paper-1",
                "question": "Is the method effective?",
                "no_answer": False,
                "answers": [
                    {
                        "answer_type": "boolean",
                        "answer": "Yes",
                        "evidence_texts": ["The method is effective."],
                        "evidence_paragraph_ids": ["paragraph-1"],
                    }
                ],
                "gold_evidence_paragraph_ids": ["paragraph-1"],
            }
        ],
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "complete",
                "split": "validation",
                "seed": 42,
                "question_count": 1,
                "qrels_path": str(qrels_path),
                "started_at": "2026-09-24T00:00:00+00:00",
                "debug": {"sample_size": "20", "config_id": "default", "variant": "CURRENT"},
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        run_dir / "predictions.jsonl",
        [
            {
                "question_id": "question-1",
                "answer": "Yes",
                "predicted_evidence": ["The method is effective."],
            }
        ],
    )
    _write_jsonl(
        run_dir / "retrieval_trace.jsonl",
        [
            {
                "question_id": "question-1",
                "final_candidates": [
                    {
                        "chunk_id": "chunk-1",
                        "source_paragraph_ids": ["paragraph-1"],
                    }
                ],
                "retrieval_rounds": [],
            }
        ],
    )
    (run_dir / "metrics.json").write_text(
        json.dumps({"per_question": [{"question_id": "question-1", "gold_evidence_recall_at_10": 1.0, "error_types": ["answer_unsupported"]}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "benchmark_root", lambda path=None: benchmark)

    case = service.get_qasper_debug_case(run_id, "question-1")
    runs = service.list_qasper_debug_runs()

    assert case is not None
    assert case.gold_paragraph_ids == ["paragraph-1"]
    assert case.metrics["Answer F1"] == 1.0
    assert case.metrics["Evidence F1"] == 1.0
    assert case.metrics["error_types"] == ["answer_unsupported"]
    assert case.error_types == ["answer_unsupported"]
    assert runs[0].status == "completed"
    assert runs[0].question_count == 1
    assert service.list_qasper_debug_cases(run_id)[0].error_types == ["answer_unsupported"]


def test_qasper_debug_comparison_pairs_matching_questions_and_bootstraps_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = tmp_path / "qasper"
    for run_id, answer_scores in (
        ("debug-qasper-validation-baseline", [0.0, 0.5]),
        ("debug-qasper-validation-candidate", [0.5, 1.0]),
    ):
        run_dir = benchmark / "results" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps({"run_id": run_id, "status": "complete", "split": "validation", "question_count": 2}),
            encoding="utf-8",
        )
        (run_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "per_question": [
                        {"question_id": f"q{index}", "official_answer_f1": score, "official_evidence_f1": score, "gold_evidence_recall_at_10": score, "MRR": score}
                        for index, score in enumerate(answer_scores, 1)
                    ]
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(service, "benchmark_root", lambda path=None: benchmark)

    result = service.compare_qasper_debug_runs(
        QasperDebugCompareRequest(
            baseline_run_id="debug-qasper-validation-baseline",
            candidate_run_id="debug-qasper-validation-candidate",
            seed=42,
            resamples=200,
        )
    )

    assert result.paired_question_count == 2
    assert result.metrics["Answer F1"]["baseline_mean"] == pytest.approx(0.25)
    assert result.metrics["Answer F1"]["candidate_mean"] == pytest.approx(0.75)
    assert result.metrics["Answer F1"]["delta"] == pytest.approx(0.5)


def test_qasper_debug_only_allows_one_queued_or_running_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeThread:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def start(self) -> None:
            return None

    monkeypatch.setattr(service, "_RUN_STATES", {})
    monkeypatch.setattr(service.threading, "Thread", FakeThread)
    request = QasperDebugRunRequest(config_id="default")

    accepted = service.start_qasper_debug_run(request, RagConfig())

    assert accepted.status == "queued"
    with pytest.raises(RuntimeError, match="already queued or running"):
        service.start_qasper_debug_run(request, RagConfig())


def test_qasper_run_history_includes_existing_benchmark_runs_and_partial_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = tmp_path / "qasper"
    run_id = "p1q4-real-dev100-r0"
    run_dir = benchmark / "results" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "dataset": "qasper",
                "status": "partial",
                "split": "validation",
                "mode": "dev",
                "limit": 100,
                "seed": 42,
                "question_count": 100,
                "started_at": "2026-09-24T00:00:00+00:00",
                "error_count": 1,
                "error": "provider timeout",
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        run_dir / "predictions.jsonl",
        [{"question_id": "q1"}, {"question_id": "q2"}],
    )
    (run_dir / "metrics.json").write_text(json.dumps({"official_qasper": {}}), encoding="utf-8")
    monkeypatch.setattr(service, "benchmark_root", lambda path=None: benchmark)

    summaries = service.list_qasper_debug_runs()

    assert len(summaries) == 1
    assert summaries[0].run_id == run_id
    assert summaries[0].status == "partial"
    assert summaries[0].completed_question_count == 2
    assert summaries[0].question_count == 100
    assert service.get_qasper_debug_run(run_id) == summaries[0]


def test_qasper_debug_chunk_catalog_pages_and_counts_gold_hit_questions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = tmp_path / "qasper"
    run_id = "debug-qasper-validation-chunks"
    run_dir = benchmark / "results" / run_id
    run_dir.mkdir(parents=True)
    qrels_path = benchmark / "qrels.jsonl"
    _write_jsonl(
        qrels_path,
        [
            {"question_id": "q1", "gold_evidence_paragraph_ids": ["p1"]},
            {"question_id": "q2", "gold_evidence_paragraph_ids": ["p1"]},
            {"question_id": "q3", "gold_evidence_paragraph_ids": ["p2"]},
        ],
    )
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "status": "complete", "qrels_path": str(qrels_path), "index": {"index_root": str(benchmark / "indexes")}}),
        encoding="utf-8",
    )

    class FakeSparseRetriever:
        def __init__(self, _path: Path) -> None:
            pass

        def list_chunks(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    chunk_id="chunk-1",
                    document_id="paper-1",
                    title="Paper",
                    text="first paragraph content",
                    section_path=["Introduction"],
                    metadata={"benchmark": {"source_paragraph_ids": ["p1"]}},
                ),
                SimpleNamespace(
                    chunk_id="chunk-2",
                    document_id="paper-1",
                    title="Paper",
                    text="second paragraph content",
                    section_path=["Results"],
                    metadata={"benchmark": {"source_paragraph_ids": ["p2"]}},
                ),
            ]

    monkeypatch.setattr(service, "benchmark_root", lambda path=None: benchmark)
    monkeypatch.setattr("backend.rag.sparse.store.BM25SparseRetriever", FakeSparseRetriever)

    first_page = service.list_qasper_debug_chunks(run_id, page=1, page_size=1)
    filtered_page = service.list_qasper_debug_chunks(run_id, query="Results")

    assert first_page.total == 2
    assert first_page.chunks[0].source_paragraph_ids == ["p1"]
    assert first_page.chunks[0].gold_question_count == 2
    assert filtered_page.total == 1
    assert filtered_page.chunks[0].section_path == ["Results"]
    assert filtered_page.chunks[0].gold_question_count == 1
