import json

import pytest

from backend.rag.evaluation_dataset import (
    RagEvaluationCase,
    RagEvaluationPrediction,
    RagGoldSpan,
)
from backend.rag.models import DocumentChunk
from backend.rag.source_span import SourceSpan
from scripts.eval_rag_production import align_source_gold, run_evaluation


def test_span_gold_rechunks_explicitly_and_stale_gold_fails(tmp_path):
    text = "Alpha uses Beta."
    span = SourceSpan.from_text(text, start_char=0, end_char=len(text), document_hash="hash")
    case = RagEvaluationCase(case_id="q", query="q", gold_spans=[RagGoldSpan(span_id="gold", document_id="d", source_span=span)])
    chunk = DocumentChunk(chunk_id="new", document_id="d", chunk_index=0, text=text, end_char=len(text), source_span=span)
    path = tmp_path / "chunks.jsonl"
    path.write_text(chunk.model_dump_json(), encoding="utf-8")
    prediction = RagEvaluationPrediction(case_id="q", ranked_chunk_ids=["new"])
    assert align_source_gold([case], [prediction], path)[0].relevant_chunk_ids == ["new"]
    chunk.source_span = span.model_copy(update={"document_hash": "new-version"})
    path.write_text(chunk.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be aligned"):
        align_source_gold([case], [prediction], path)


def test_runner_freezes_outputs_and_refuses_missing_data_or_overwrite(tmp_path):
    cases, predictions = tmp_path / "cases.json", tmp_path / "predictions.json"
    cases.write_text(json.dumps([{"case_id": "q", "query": "q", "relevant_chunk_ids": ["a"]}]))
    predictions.write_text(json.dumps([{"case_id": "q", "ranked_chunk_ids": ["a"]}]))
    first = run_evaluation(cases, predictions, tmp_path / "first")
    second = run_evaluation(cases, predictions, tmp_path / "second")
    assert first == second
    assert (tmp_path / "first/metrics.json").read_bytes() == (tmp_path / "second/metrics.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_evaluation(cases, predictions, tmp_path / "first")
    with pytest.raises(FileNotFoundError):
        run_evaluation(tmp_path / "missing", predictions, tmp_path / "other")


def test_real_import_requires_verified_original_files(tmp_path):
    import hashlib

    cases, predictions = tmp_path / "cases.json", tmp_path / "predictions.json"
    cases.write_text(json.dumps([{"case_id": "q", "query": "q"}]))
    predictions.write_text(json.dumps([{"case_id": "q"}]))
    with pytest.raises(ValueError, match="source run manifest"):
        run_evaluation(cases, predictions, tmp_path / "missing", dataset_kind="real_import")
    raw = tmp_path / "source.txt"
    raw.write_text("original")
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(json.dumps({"dataset_kind": "real_import", "raw_files": [
        {"path": "source.txt", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()},
    ]}))
    assert run_evaluation(cases, predictions, tmp_path / "valid", dataset_kind="real_import", source_manifest=manifest)["status"] == "complete"
    raw.write_text("changed")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        run_evaluation(cases, predictions, tmp_path / "invalid", dataset_kind="real_import", source_manifest=manifest)


def test_correct_empty_answer_is_not_exported_as_a_retrieval_bad_case(tmp_path):
    cases, predictions = tmp_path / "cases.json", tmp_path / "predictions.json"
    cases.write_text(json.dumps([{"case_id": "q", "query": "q", "no_answer": True, "categories": ["no_answer"]}]))
    predictions.write_text(json.dumps([{"case_id": "q", "ranked_chunk_ids": []}]))
    run_evaluation(cases, predictions, tmp_path / "run")
    assert (tmp_path / "run/bad_cases.jsonl").read_text() == ""
