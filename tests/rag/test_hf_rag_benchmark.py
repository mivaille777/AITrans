import json
from types import SimpleNamespace

import pytest

from app.ai.errors import AIResponseError
from backend.rag.source_span import resolve_source_span
from scripts import run_hf_graph_benchmark
from scripts.run_hf_graph_benchmark import prepare
from scripts.run_hf_rag_benchmark import gate, load_cases, make_chunks


def test_full_corpus_is_kept_when_sampling_queries(tmp_path):
    corpus = [{"_id": "a", "text": "first"}, {"_id": "b", "text": "distractor"}]
    (tmp_path / "qrels").mkdir()
    for name, rows in (
        ("corpus.jsonl", corpus),
        ("queries.jsonl", [{"_id": "q", "text": "question"}]),
        ("qrels/train.jsonl", [{"query-id": "q", "corpus-id": "a", "score": 1}]),
    ):
        (tmp_path / name).write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    loaded, _, gold, selected, _ = load_cases(tmp_path, "scifact", "train", 1, 42)
    assert loaded == corpus
    assert selected == ["q"]
    assert gold["q"] == {"a": 1}
    chunks = make_chunks(loaded, "en", str(tmp_path))
    assert resolve_source_span(chunks[1].source_span, "distractor") == "distractor"


def test_invalid_qrels_cannot_silently_drop_cases(tmp_path):
    (tmp_path / "qrels").mkdir()
    (tmp_path / "corpus.jsonl").write_text('{"_id":"a","text":"first"}', encoding="utf-8")
    (tmp_path / "queries.jsonl").write_text('{"_id":"q","text":"question"}', encoding="utf-8")
    (tmp_path / "qrels/train.jsonl").write_text(
        '{"query-id":"q","corpus-id":"missing","score":1}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing query/corpus"):
        load_cases(tmp_path, "scifact", "train", None, 42)


def test_retrieval_pass_does_not_claim_citation_acceptance():
    metrics = {"Recall@5": .9, "MRR@20": .8, "warm_retrieval_p95_ms": 400,
               "query_count": 100, "degraded_queries": 0}
    result = gate(metrics)
    assert result["retrieval_status"] == "PASS"
    assert result["overall_status"] == "BLOCKED"
    assert result["citation_accuracy"] is None
    metrics["degraded_queries"] = 1
    assert gate(metrics)["retrieval_status"] == "FAIL"


def test_multihop_preparation_preserves_distractors_and_both_gold_documents():
    rows = [{"id": "q", "question": "question", "type": "compositional", "evidences": [],
             "context": {"title": ["first", "second", "distractor"],
                         "sentences": [["first fact"], ["second fact"], ["unrelated"]]},
             "supporting_facts": {"title": ["first", "second"], "sent_id": [0, 0]}}]
    chunks, cases = prepare(rows, 1, "public-source")
    assert len(chunks) == 3
    assert len(cases[0]["gold_ids"]) == 2
    assert all(chunk.source_span is not None for chunk in chunks)
    rows[0]["supporting_facts"]["sent_id"][0] = 1
    with pytest.raises(ValueError, match="outside source"):
        prepare(rows, 1, "public-source")


def test_failed_graph_build_cannot_be_reported_complete(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps({"id": "q", "question": "question", "type": "compositional",
        "evidences": [], "context": {"title": ["first"], "sentences": [["first fact"]]},
        "supporting_facts": {"title": ["first"], "sent_id": [0]}}), encoding="utf-8")
    service = SimpleNamespace(provider_name="test", model="test", close=lambda: None)
    monkeypatch.setattr(run_hf_graph_benchmark, "LLMGateway", lambda: SimpleNamespace(
        create_text_service=lambda purpose: service))

    def failed_build(*args, **kwargs):
        raise AIResponseError("payment required", status_code=402)

    monkeypatch.setattr(run_hf_graph_benchmark.GraphIndexer, "build_generation", failed_build)
    output = tmp_path / "result"
    monkeypatch.setattr("sys.argv", ["benchmark", "--source", str(source), "--output", str(output)])
    assert run_hf_graph_benchmark.main() == 2
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "partial"
    assert manifest["graph_acceptance"] == "BLOCKED"
    assert manifest["error_count"] == 1
    assert manifest["source_question_count"] == 1
