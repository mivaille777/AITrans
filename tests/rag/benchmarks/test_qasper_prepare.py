from __future__ import annotations

import json

from scripts.prepare_qasper import prepare_dataset


def test_prepare_writes_normalized_corpus_qrels_and_manifest(tmp_path) -> None:
    raw_path = tmp_path / "source.json"
    raw_path.write_text(
        json.dumps(
            {
                "paper-prepare": {
                    "title": "Preparation paper",
                    "abstract": "An abstract paragraph.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": ["The final evidence paragraph is stable."],
                        }
                    ],
                    "qas": [
                        {
                            "question_id": "question-prepare",
                            "question": "What is stable?",
                            "answers": [
                                {
                                    "annotation_id": "answer-prepare",
                                    "answer": {"free_form_answer": "The paragraph."},
                                    "evidence": [
                                        "The final evidence paragraph is stable."
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

    summary = prepare_dataset(root=tmp_path / "benchmark", raw_json=raw_path)

    assert summary["paper_count"] == 1
    assert summary["question_count"] == 1
    assert summary["alignment_target_met"]
    normalized = next(
        json.loads(line)
        for line in (tmp_path / "benchmark/normalized/validation/papers.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert normalized["document"]["document"]["document_id"] == (
        "qasper:validation:paper-prepare"
    )
    qrel = json.loads(
        (tmp_path / "benchmark/qrels/validation.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    assert qrel["expected_retrieval"] is True
    assert qrel["answers"][0]["evidence_paragraph_ids"] == [
        "qasper:validation:paper-prepare:p1"
    ]
