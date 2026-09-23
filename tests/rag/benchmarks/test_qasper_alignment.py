from __future__ import annotations

import json

from backend.rag.benchmarks.qasper.alignment import align_qasper_evidence
from backend.rag.benchmarks.qasper.loader import load_qasper


def test_alignment_maps_whitespace_variants_and_reports_unmatched_evidence(tmp_path) -> None:
    raw = {
        "paper-y": {
            "title": "Alignment paper",
            "abstract": "",
            "full_text": [
                {"section_name": "Introduction", "paragraphs": ["Evidence is retained."]}
            ],
            "qas": [
                {
                    "question_id": "q-align",
                    "question": "What is retained?",
                    "answers": [
                        {
                            "annotation_id": "a-good",
                            "answer": {"free_form_answer": "Evidence."},
                            "evidence": ["  Evidence\n is retained.  "],
                        },
                        {
                            "annotation_id": "a-missing",
                            "answer": {"free_form_answer": "Something else."},
                            "evidence": ["This evidence is absent from the source paper."],
                        },
                    ],
                }
            ],
        }
    }
    raw_path = tmp_path / "alignment.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    dataset = load_qasper(raw_path)

    alignment = align_qasper_evidence(dataset)

    answers = alignment.by_question["q-align"]
    assert answers[0].paragraph_ids == ("qasper:validation:paper-y:p0",)
    assert answers[1].paragraph_ids == ()
    assert alignment.total_evidence_items == 2
    assert alignment.aligned_evidence_items == 1
    assert alignment.coverage == 0.5
    assert len(alignment.errors) == 1
    assert alignment.errors[0].annotation_id == "a-missing"
    assert alignment.errors[0].reason == "no_paragraph_match"


def test_alignment_resolves_section_markers_and_reports_non_text_floats(tmp_path) -> None:
    raw = {
        "paper-z": {
            "title": "Section evidence paper",
            "full_text": [
                {
                    "section_name": "Results ::: Emotion Analysis",
                    "paragraphs": ["This section contains the emotion analysis."],
                }
            ],
            "qas": [
                {
                    "question_id": "q-section",
                    "question": "What section is relevant?",
                    "answers": [
                        {
                            "annotation_id": "a-section",
                            "answer": {"free_form_answer": "Emotion analysis."},
                            "evidence": [
                                "Results ::: Emotion Analysis",
                                "FLOAT SELECTED: Table 2: Results",
                            ],
                        }
                    ],
                }
            ],
        }
    }
    raw_path = tmp_path / "section-evidence.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    alignment = align_qasper_evidence(load_qasper(raw_path))

    answer = alignment.by_question["q-section"][0]
    assert answer.paragraph_ids == ("qasper:validation:paper-z:p0",)
    assert not answer.evidence_complete
    assert alignment.coverage == 0.5
    assert alignment.text_coverage == 1.0
    assert alignment.errors[0].reason == "non_text_float_evidence"
