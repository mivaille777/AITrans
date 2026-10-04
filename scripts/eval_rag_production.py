from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.common import atomic_write_json, atomic_write_jsonl
from backend.rag.evaluation import evaluate_rag
from backend.rag.evaluation_dataset import (
    RagGoldSpan,
    load_evaluation_dataset,
    load_evaluation_predictions,
)
from backend.rag.evaluation_protocol import ClaimAssessment
from backend.rag.models import DocumentChunk


def align_source_gold(cases, predictions, catalogue):
    chunks = [DocumentChunk.model_validate(json.loads(line)) for line in Path(catalogue).read_text(encoding="utf-8").splitlines() if line.strip()]
    mapped = []
    for case in cases:
        grades = {}
        for gold in case.gold_spans:
            matches = []
            for chunk in chunks:
                span = chunk.source_span
                if span is None or chunk.document_id != gold.document_id:
                    continue
                target = gold.source_span
                if (span.document_hash != target.document_hash or span.document_text_hash != target.document_text_hash
                        or span.start_char > target.start_char or span.end_char < target.end_char):
                    continue
                quote = chunk.text[target.start_char - span.start_char:target.end_char - span.start_char]
                if hashlib.sha256(quote.encode()).hexdigest() == target.quote_hash:
                    matches.append(chunk.chunk_id)
            if not matches:
                raise ValueError(f"source gold cannot be aligned: {case.case_id}/{gold.span_id}")
            grades.update({key: max(grades.get(key, 0), gold.relevance_grade) for key in matches})
        mapped.append(case.model_copy(update={"relevant_chunk_ids": list(grades), "relevance_grades": grades}) if case.gold_spans else case)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    for prediction in predictions:
        for key in prediction.ranked_chunk_ids:
            if key not in by_id:
                raise ValueError(f"prediction chunk is absent from aligned catalogue: {key}")
            chunk = by_id[key]
            prediction.chunk_document_ids[key] = chunk.document_id
            if chunk.source_span is not None:
                prediction.chunk_spans[key] = RagGoldSpan(span_id=key, document_id=chunk.document_id, source_span=chunk.source_span)
    return mapped


def validate_judge_calibration(labels, calibration):
    judged = [label for label in labels if label.method == "calibrated_judge"]
    if not judged:
        return None
    if calibration is None:
        raise ValueError("judge assessments require a qualified calibration record")
    raw = Path(calibration).read_bytes()
    record = json.loads(raw)
    if (
        record.get("qualified") is not True
        or record.get("errors") != 0
        or record.get("N", 0) < 30
        or not 0.90 <= record.get("binary_agreement", -1) <= 1.0
        or not 0.90 <= (record.get("supported_precision") or -1) <= 1.0
    ):
        raise ValueError("judge calibration has not met qualification criteria")
    fingerprint = hashlib.sha256(raw).hexdigest()
    if any(label.calibration_id != fingerprint for label in judged):
        raise ValueError("judge assessment calibration_id must match the record SHA256")
    return fingerprint


def run_evaluation(dataset, predictions, output, *, dataset_kind="synthetic", assessments=None, catalogue=None, source_manifest=None, judge_calibration=None):
    """Evaluate frozen outputs; retrieval generation remains the existing benchmark's job."""
    cases = load_evaluation_dataset(dataset)
    answers = load_evaluation_predictions(predictions)
    if not cases:
        raise ValueError("evaluation dataset must not be empty")
    source = None
    if dataset_kind != "synthetic":
        if source_manifest is None:
            raise ValueError("non-synthetic evaluation requires a frozen source run manifest")
        source = json.loads(Path(source_manifest).read_text(encoding="utf-8"))
        if dataset_kind == "qasper_known_paper":
            from backend.rag.benchmarks.qasper.protocol import audit_qasper_run
            audit = audit_qasper_run(Path(source_manifest).parent, require_answer_generation=False)
            if not audit["ok"]:
                raise ValueError(f"QASPER source audit failed: {audit['issues']}")
        elif source.get("dataset_kind") != dataset_kind or not source.get("raw_files"):
            raise ValueError("original-file evaluation requires matching dataset kind and raw file fingerprints")
        else:
            for entry in source["raw_files"]:
                raw_path = Path(source_manifest).parent / entry["path"]
                if hashlib.sha256(raw_path.read_bytes()).hexdigest() != entry["sha256"]:
                    raise ValueError(f"raw file fingerprint mismatch: {entry['path']}")
    labels = [] if assessments is None else [
        ClaimAssessment.model_validate(item) for item in json.loads(Path(assessments).read_text(encoding="utf-8"))
    ]
    calibration_hash = validate_judge_calibration(labels, judge_calibration)
    # Stable source gold requires explicit alignment, never silent chunk-ID fallback.
    if any(case.gold_spans for case in cases):
        if catalogue is None:
            raise ValueError("source-span gold requires an aligned catalogue")
        cases = align_source_gold(cases, answers, catalogue)
    report = evaluate_rag(cases, answers, assessments=labels)
    destination = Path(output)
    if (destination / "manifest.json").exists():
        raise FileExistsError("run output already exists; choose a new run directory")
    manifest = {"schema_version": 1, "dataset_kind": dataset_kind, "status": "complete",
                "cases": len(cases), "answer_acceptance": "assessed" if labels else "deferred",
                "fingerprints": {"dataset": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
                                 "predictions": hashlib.sha256(Path(predictions).read_bytes()).hexdigest()},
                "files": {"metrics": "metrics.json", "per_case": "per_case.jsonl", "bad_cases": "bad_cases.jsonl"}}
    if catalogue is not None:
        manifest["fingerprints"]["catalogue"] = hashlib.sha256(Path(catalogue).read_bytes()).hexdigest()
    if assessments is not None:
        manifest["fingerprints"]["assessments"] = hashlib.sha256(Path(assessments).read_bytes()).hexdigest()
    if calibration_hash is not None:
        manifest["fingerprints"]["judge_calibration"] = calibration_hash
    if source_manifest is not None:
        manifest["fingerprints"]["source_manifest"] = hashlib.sha256(Path(source_manifest).read_bytes()).hexdigest()
        manifest["source_run"] = source
    atomic_write_json(destination / "metrics.json", report.model_dump(mode="json"))
    atomic_write_jsonl(destination / "per_case.jsonl", [item.model_dump(mode="json") for item in report.cases])
    retrieval_gold_ids = {case.case_id for case in cases if case.graded_relevance}
    atomic_write_jsonl(destination / "bad_cases.jsonl", [item.model_dump(mode="json") for item in report.cases
                                                       if (item.case_id in retrieval_gold_ids and item.recall_at_10 < 1)
                                                       or item.no_answer_correct is False])
    atomic_write_json(destination / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Audit frozen RAG predictions against independent gold.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--assessments")
    parser.add_argument("--judge-calibration")
    parser.add_argument("--catalogue")
    parser.add_argument("--source-manifest")
    parser.add_argument("--dataset-kind", choices=["synthetic", "qasper_known_paper", "real_import", "unknown_document"], default="synthetic")
    args = parser.parse_args()
    print(json.dumps(run_evaluation(args.dataset, args.predictions, args.output,
                                   dataset_kind=args.dataset_kind, assessments=args.assessments, catalogue=args.catalogue,
                                   source_manifest=args.source_manifest, judge_calibration=args.judge_calibration)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
