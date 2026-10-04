"""Replay frozen current QASPER retrieval through the existing answer service.

No retrieval rerun, gold document filtering changes or gold input to the model.
Official answer scoring is separate from independent semantic citation accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ai.errors import AIError
from backend.rag.benchmarks.common import atomic_write_json, atomic_write_jsonl
from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run
from backend.rag.benchmarks.qasper.runner import (
    GroundedQasperAnswerer,
    QasperAnswerInput,
)
from backend.rag.models import (
    RetrievalCandidate,
    RetrievalContextWindow,
    RetrievalResult,
)
from backend.rag.sparse import BM25SparseRetriever
from scripts.run_hf_sparse_benchmark import _rows, _sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--answer-contract", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output must be new")
    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "complete" or manifest["error_count"]:
        raise ValueError("retrieval source must be complete without errors")
    source = manifest["source_path"]
    if _sha256(Path(source)) != manifest["source_sha256"]:
        raise ValueError("QASPER source hash changed")
    store = BM25SparseRetriever(Path(manifest["index"]["index_root"]) / "bm25_index.json")
    predictions = {row["question_id"]: row for row in _rows(args.run / "predictions.jsonl")}
    traces = _rows(args.run / "retrieval_trace.jsonl")
    args.output.mkdir(parents=True)
    contract = (json.loads(args.answer_contract.read_text(encoding="utf-8"))
                if args.answer_contract else None)
    answerer = GroundedQasperAnswerer(answer_contract=contract,
        answer_contract_sha256=_sha256(args.answer_contract) if args.answer_contract else None)
    results, output_traces, errors = [], [], []
    try:
        for position, trace in enumerate(traces, 1):
            candidates = []
            for item in trace["final_candidates"]:
                chunk = store.get_chunk(item["chunk_id"])
                if chunk is None or chunk.text != item["text"] or chunk.document_id != trace["scope_document_id"]:
                    raise ValueError("frozen retrieval no longer matches the source catalogue")
                window = item.get("context_window")
                context = None
                if window:
                    neighbors = [store.get_chunk(cid) for cid in window["chunk_ids"]]
                    if any(c is None or c.document_id != chunk.document_id for c in neighbors):
                        raise ValueError("frozen context has missing or out-of-scope chunks")
                    context = RetrievalContextWindow(anchor_chunk_id=window["anchor_chunk_id"],
                        chunks=neighbors, text=window["text"], token_count=window["token_count"])
                candidates.append(RetrievalCandidate(chunk=chunk, rank=item["rank"],
                    context_window=context, metadata=item["metadata"],
                    **{f"{key}_score": value for key, value in item["scores"].items()}))
            prediction = dict(predictions[trace["question_id"]])
            try:
                generated = answerer(QasperAnswerInput(prediction["question_id"],
                    prediction["paper_id"], prediction["question"]),
                    RetrievalResult(query=trace["query"], candidates=candidates,
                                    metadata=trace["retrieval_metadata"]))
                prediction.update(answer=generated.answer, user_visible_answer=generated.user_visible_answer,
                    answer_generation={"metadata": generated.metadata or {}, "provider": generated.provider,
                                       "model": generated.model, "latency_ms": generated.latency_ms})
            except AIError as exc:
                prediction["error"] = f"{type(exc).__name__}: {exc}"
                errors.append({"question_id": prediction["question_id"], "error": prediction["error"]})
            results.append(prediction)
            output_traces.append({**trace, "answer": prediction["answer"],
                                  "answer_generation": prediction["answer_generation"], "error": prediction["error"]})
            atomic_write_jsonl(args.output / "predictions.jsonl", results)
            atomic_write_jsonl(args.output / "retrieval_trace.jsonl", output_traces)
            print(f"answers: {position}/{len(traces)}", flush=True)
        manifest.update(run_id=args.output.name, status="complete" if not errors else "partial",
            error_count=len(errors), answer_count=len(results) - len(errors),
            answer_generation={"enabled": True, "provider": answerer.provider, "model": answerer.model},
            answer_model={"provider": answerer.provider, "model": answerer.model},
            answer_contract=answerer.answer_contract_manifest,
            source_retrieval_run=str(args.run.resolve()),
            source_retrieval_hashes={file: _sha256(args.run / file)
                                    for file in ("manifest.json", "retrieval_trace.jsonl", "predictions.jsonl")},
            semantic_citation_accuracy_status="not measured: independent claim/citation assessments required")
        atomic_write_json(args.output / "manifest.json", manifest)
        atomic_write_jsonl(args.output / "errors.jsonl", errors)
        metrics = evaluate_qasper_run(args.output)
        print(json.dumps({"official": metrics["official_qasper"],
                          "answer_behavior": metrics["answer_behavior"]}), flush=True)
    finally:
        answerer.close()
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
