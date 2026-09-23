from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.models.rag_debug import (
    QasperDebugCase,
    QasperDebugCaseIndex,
    QasperDebugChunk,
    QasperDebugChunkPage,
    QasperDebugCompareRequest,
    QasperDebugCompareResponse,
    QasperDebugRunRequest,
    QasperDebugRunSummary,
)
from backend.rag.benchmarks.common import atomic_write_json, benchmark_root, read_json
from backend.rag.config import RagConfig

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_STATE_LOCK = threading.RLock()
_RUN_STATES: dict[str, dict[str, Any]] = {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _safe_run_path(run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id) or not run_id.startswith("debug-qasper-"):
        raise ValueError("Invalid QASPER debug run id.")
    root = benchmark_root() / "results"
    run_path = (root / run_id).resolve()
    if root.resolve() not in run_path.parents:
        raise ValueError("Invalid QASPER debug run path.")
    return run_path


def _summary_from_manifest(run_id: str, manifest: dict[str, Any]) -> QasperDebugRunSummary:
    raw_status = str(manifest.get("status", "queued"))
    status = {
        "complete": "completed",
        "partial": "completed",
        "retrieval_complete": "completed",
        "baseline_complete": "completed",
    }.get(raw_status, raw_status)
    if status not in {"queued", "running", "completed", "failed", "cancelled"}:
        status = "failed"
    metrics_path = _safe_run_path(run_id) / "metrics.json"
    metrics = read_json(metrics_path) or {}
    debug = manifest.get("debug", {})
    if not isinstance(debug, dict):
        debug = {}
    variant_info = manifest.get("ablation_variant", {})
    variant = str(debug.get("variant") or (variant_info.get("variant_id") if isinstance(variant_info, dict) else "CURRENT") or "CURRENT")
    if manifest.get("adaptive_variant"):
        variant = f"adaptive:{manifest['adaptive_variant']}"
    elif manifest.get("evidence_selection_variant"):
        variant = f"evidence:{manifest['evidence_selection_variant']}"
    return QasperDebugRunSummary(
        run_id=run_id,
        status=status,
        split=str(manifest.get("split", debug.get("split", "validation"))),
        sample_size=str(debug.get("sample_size", manifest.get("limit") or "full")),
        seed=int(manifest.get("seed", debug.get("seed", 42)) or 0),
        config_id=str(debug.get("config_id", "default")),
        variant=variant,
        question_count=int(manifest.get("question_count", 0) or 0),
        error=str(manifest.get("error", "") or ""),
        started_at=str(manifest.get("started_at", "") or ""),
        completed_at=str(manifest.get("completed_at", "") or ""),
        metrics=metrics,
    )


def _summary_from_state(run_id: str, state: dict[str, Any]) -> QasperDebugRunSummary:
    return QasperDebugRunSummary(
        run_id=run_id,
        status=str(state.get("status", "queued")),
        split=str(state.get("split", "validation")),
        sample_size=str(state.get("sample_size", "20")),
        seed=int(state.get("seed", 42)),
        config_id=str(state.get("config_id", "default")),
        variant=str(state.get("variant", "CURRENT")),
        question_count=int(state.get("question_count", 0)),
        error=str(state.get("error", "")),
        started_at=str(state.get("started_at", "")),
        completed_at=str(state.get("completed_at", "")),
        metrics=state.get("metrics", {}),
    )


def list_qasper_debug_runs() -> list[QasperDebugRunSummary]:
    results_root = benchmark_root() / "results"
    summaries: dict[str, QasperDebugRunSummary] = {}
    if results_root.is_dir():
        for manifest_path in results_root.glob("debug-qasper-*/manifest.json"):
            run_id = manifest_path.parent.name
            try:
                manifest = read_json(manifest_path)
                if manifest:
                    summaries[run_id] = _summary_from_manifest(run_id, manifest)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    with _STATE_LOCK:
        for run_id, state in _RUN_STATES.items():
            summaries.setdefault(run_id, _summary_from_state(run_id, state))
    return sorted(summaries.values(), key=lambda item: item.started_at, reverse=True)


def get_qasper_debug_run(run_id: str) -> QasperDebugRunSummary | None:
    try:
        manifest = read_json(_safe_run_path(run_id) / "manifest.json")
    except ValueError:
        return None
    if manifest:
        return _summary_from_manifest(run_id, manifest)
    with _STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        return _summary_from_state(run_id, state) if state else None


def start_qasper_debug_run(
    request: QasperDebugRunRequest,
    config: RagConfig,
) -> QasperDebugRunSummary:
    run_id = f"debug-qasper-{request.split}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
    state = {
        "status": "queued",
        "split": request.split,
        "sample_size": request.sample_size,
        "seed": request.seed,
        "config_id": request.config_id,
        "variant": request.variant,
        "started_at": datetime.now(UTC).isoformat(),
    }
    with _STATE_LOCK:
        if any(item.get("status") in {"queued", "running"} for item in _RUN_STATES.values()):
            raise RuntimeError("A QASPER debug run is already queued or running.")
        _RUN_STATES[run_id] = state
    thread = threading.Thread(
        target=_execute_qasper_debug_run,
        args=(run_id, request.model_dump(mode="json"), config.model_dump(mode="json")),
        name=f"{run_id}-worker",
        daemon=True,
    )
    thread.start()
    return _summary_from_state(run_id, state)


def _execute_qasper_debug_run(run_id: str, request_data: dict[str, Any], config_data: dict[str, Any]) -> None:
    with _STATE_LOCK:
        state = _RUN_STATES[run_id]
        state["status"] = "running"
    try:
        from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run
        from backend.rag.benchmarks.qasper.loader import (
            download_qasper_split,
            load_qasper,
        )
        from backend.rag.benchmarks.qasper.runner import (
            GroundedQasperAnswerer,
            run_qasper_benchmark,
        )

        request = QasperDebugRunRequest.model_validate(request_data)
        root = benchmark_root()
        source_split = "dev" if request.split == "validation" else request.split
        source_path = download_qasper_split(
            source_split,
            root / "raw",
            manifest_directory=root / "manifests",
        )
        dataset = load_qasper(source_path, split=request.split)
        size_to_limit = {"20": 20, "100": 100, "full": None}
        sample_size = request.sample_size
        mode = {"20": "smoke", "100": "dev", "full": "full"}[sample_size]
        selected_variant = request.variant
        runner_options: dict[str, Any] = {}
        if selected_variant.startswith("adaptive:"):
            runner_options["adaptive_variant"] = selected_variant.partition(":")[2]
        elif selected_variant.startswith("evidence:"):
            runner_options["evidence_selection_variant"] = selected_variant.partition(":")[2]
        elif selected_variant.casefold() != "current":
            runner_options["variant"] = selected_variant
        answerer = GroundedQasperAnswerer() if request.include_answer else None
        try:
            result = run_qasper_benchmark(
                dataset,
                root=root,
                mode=mode,
                limit=size_to_limit[sample_size],
                seed=request.seed,
                config=RagConfig.model_validate(config_data),
                answerer=answerer,
                run_id=run_id,
                **runner_options,
            )
            metrics = evaluate_qasper_run(result.run_directory, root=root)
            manifest_path = result.manifest_path
            manifest = read_json(manifest_path) or {}
            manifest["debug"] = {
                "config_id": request.config_id,
                "sample_size": request.sample_size,
                "variant": request.variant,
                "include_answer": request.include_answer,
            }
            atomic_write_json(manifest_path, manifest)
            with _STATE_LOCK:
                state.update(
                    {
                        "status": "completed",
                        "question_count": result.question_count,
                        "completed_at": datetime.now(UTC).isoformat(),
                        "metrics": metrics,
                    }
                )
        finally:
            if answerer is not None:
                answerer.close()
    except Exception as exc:  # noqa: BLE001 - keep the failure available to Debug Studio.
        with _STATE_LOCK:
            state.update(
                {
                    "status": "failed",
                    "error": str(exc) or exc.__class__.__name__,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )


def _run_artifacts(run_id: str) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    run_path = _safe_run_path(run_id)
    manifest = read_json(run_path / "manifest.json")
    if manifest is None:
        raise FileNotFoundError("QASPER debug run has no benchmark manifest yet.")
    qrels_path = Path(str(manifest.get("qrels_path", ""))).expanduser()
    if not qrels_path.is_absolute():
        qrels_path = benchmark_root() / qrels_path
    qrels = {str(row["question_id"]): row for row in _read_jsonl(qrels_path)}
    predictions = {str(row["question_id"]): row for row in _read_jsonl(run_path / "predictions.jsonl")}
    traces = {str(row["question_id"]): row for row in _read_jsonl(run_path / "retrieval_trace.jsonl")}
    return run_path, manifest, qrels, predictions, traces


def list_qasper_debug_cases(run_id: str) -> list[QasperDebugCaseIndex]:
    run_path, _, qrels, _, _ = _run_artifacts(run_id)
    metrics_payload = read_json(run_path / "metrics.json") or {}
    per_question = metrics_payload.get("per_question", [])
    error_types_by_question = {
        str(item.get("question_id")): [str(value) for value in item.get("error_types", [])]
        for item in per_question
        if isinstance(item, dict) and isinstance(item.get("error_types", []), list)
    } if isinstance(per_question, list) else {}
    return [
        QasperDebugCaseIndex(
            question_id=question_id,
            paper_id=str(qrel.get("paper_id", "")),
            question=str(qrel.get("question", "")),
            no_answer=bool(qrel.get("no_answer", False)),
            gold_paragraph_ids=[str(value) for value in qrel.get("gold_evidence_paragraph_ids", []) if value],
            error_types=error_types_by_question.get(question_id, []),
        )
        for question_id, qrel in qrels.items()
    ]


def get_qasper_debug_case(run_id: str, question_id: str) -> QasperDebugCase | None:
    run_path, _, qrels, predictions, traces = _run_artifacts(run_id)
    qrel = qrels.get(question_id)
    if qrel is None:
        return None
    prediction = predictions.get(question_id, {})
    trace = traces.get(question_id, {})
    metrics_payload = read_json(run_path / "metrics.json") or {}
    per_question = metrics_payload.get("per_question", [])
    case_metrics = next(
        (item for item in per_question if isinstance(item, dict) and item.get("question_id") == question_id),
        {},
    ) if isinstance(per_question, list) else {}
    from third_party.qasper.official_evaluator import evaluate as evaluate_official

    references = [
        {
            "answer": str(answer.get("answer", "")),
            "evidence": [str(value) for value in answer.get("evidence_texts", [])],
            "type": str(answer.get("answer_type", "abstractive")),
        }
        for answer in qrel.get("answers", [])
        if isinstance(answer, dict)
    ]
    official_case = evaluate_official(
        {question_id: references},
        {question_id: {"answer": str(prediction.get("answer", "")), "evidence": prediction.get("predicted_evidence", [])}},
    ) if references else {}
    return QasperDebugCase(
        question_id=question_id,
        paper_id=str(qrel.get("paper_id", "")),
        question=str(qrel.get("question", "")),
        no_answer=bool(qrel.get("no_answer", False)),
        gold_paragraph_ids=[str(value) for value in qrel.get("gold_evidence_paragraph_ids", []) if value],
        error_types=[str(value) for value in case_metrics.get("error_types", []) if value],
        qrel=qrel,
        prediction=prediction,
        trace=trace,
        metrics={**case_metrics, **official_case},
    )


def compare_qasper_debug_runs(
    request: QasperDebugCompareRequest,
) -> QasperDebugCompareResponse:
    run_summaries = {
        run_id: get_qasper_debug_run(run_id)
        for run_id in (request.baseline_run_id, request.candidate_run_id)
    }
    if any(summary is None for summary in run_summaries.values()):
        raise KeyError("QASPER debug run not found")
    baseline_summary = run_summaries[request.baseline_run_id]
    candidate_summary = run_summaries[request.candidate_run_id]
    if baseline_summary is None or candidate_summary is None:
        raise KeyError("QASPER debug run not found")
    if baseline_summary.status != "completed" or candidate_summary.status != "completed":
        raise ValueError("both QASPER runs must be completed before comparison")
    if baseline_summary.split != candidate_summary.split:
        raise ValueError("paired comparison requires runs from the same dataset split")

    baseline_metrics = read_json(_safe_run_path(request.baseline_run_id) / "metrics.json") or {}
    candidate_metrics = read_json(_safe_run_path(request.candidate_run_id) / "metrics.json") or {}
    baseline_cases = baseline_metrics.get("per_question", [])
    candidate_cases = candidate_metrics.get("per_question", [])
    if not isinstance(baseline_cases, list) or not isinstance(candidate_cases, list):
        raise TypeError("QASPER run metrics do not contain per-question results")
    from backend.rag.benchmarks.qasper.statistics import paired_bootstrap

    paired = paired_bootstrap(
        baseline_cases,
        candidate_cases,
        seed=request.seed,
        resamples=request.resamples,
    )
    return QasperDebugCompareResponse(
        baseline_run_id=request.baseline_run_id,
        candidate_run_id=request.candidate_run_id,
        paired_question_count=int(paired["paired_question_count"]),
        seed=request.seed,
        resamples=request.resamples,
        metrics=paired["metrics"],
    )


def list_qasper_debug_chunks(
    run_id: str,
    *,
    page: int = 1,
    page_size: int = 50,
    query: str = "",
) -> QasperDebugChunkPage:
    _, manifest, qrels, _, _ = _run_artifacts(run_id)
    index_root = Path(str(manifest.get("index", {}).get("index_root", ""))).expanduser()
    if not index_root.is_absolute():
        index_root = benchmark_root() / index_root
    from backend.rag.sparse.store import BM25SparseRetriever

    chunks = BM25SparseRetriever(index_root / "bm25_index.json").list_chunks()
    paragraph_questions: dict[str, set[str]] = {}
    for question_id, qrel in qrels.items():
        for paragraph_id in qrel.get("gold_evidence_paragraph_ids", []):
            paragraph_questions.setdefault(str(paragraph_id), set()).add(question_id)
    rows = [
        QasperDebugChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            title=chunk.title,
            text=chunk.text,
            section_path=chunk.section_path,
            source_paragraph_ids=[str(value) for value in chunk.metadata.get("benchmark", {}).get("source_paragraph_ids", [])],
            gold_question_count=len({qid for pid in chunk.metadata.get("benchmark", {}).get("source_paragraph_ids", []) for qid in paragraph_questions.get(str(pid), set())}),
        )
        for chunk in chunks
    ]
    normalized_query = query.strip().casefold()
    if normalized_query:
        rows = [
            item
            for item in rows
            if normalized_query
            in " ".join(
                (
                    item.chunk_id,
                    item.title,
                    item.text,
                    *item.section_path,
                    *item.source_paragraph_ids,
                )
            ).casefold()
        ]
    start = (page - 1) * page_size
    return QasperDebugChunkPage(
        chunks=rows[start : start + page_size],
        total=len(rows),
        page=page,
        page_size=page_size,
    )


__all__ = [
    "compare_qasper_debug_runs",
    "get_qasper_debug_case",
    "get_qasper_debug_run",
    "list_qasper_debug_cases",
    "list_qasper_debug_chunks",
    "list_qasper_debug_runs",
    "start_qasper_debug_run",
]
