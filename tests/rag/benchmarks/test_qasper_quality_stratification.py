from __future__ import annotations

from backend.rag.benchmarks.qasper.evaluator import (
    _qasper_question_category,
    _quality_stratification,
)


def test_question_category_uses_per_annotator_gold_section_breadth() -> None:
    assert _qasper_question_category(
        {
            "answers": [
                {
                    "answer_type": "extractive",
                    "evidence_paragraph_ids": ["p1", "p2"],
                    "evidence_section_indices": [1],
                    "evidence_complete": True,
                },
                {
                    "answer_type": "extractive",
                    "evidence_paragraph_ids": ["p3"],
                    "evidence_section_indices": [2, 3],
                    "evidence_complete": True,
                },
            ]
        }
    ) == "cross_section"
    assert _qasper_question_category({"no_answer": True, "answers": []}) == "unanswerable"


def test_quality_strata_report_independent_denominators_and_multilabel_types() -> None:
    cases = [
        {
            "answer_types": ["boolean", "extractive"],
            "mapped_gold_evidence": True,
            "question_category": "local",
            "relevant_chunk_count": 1,
            "official_answer_f1": 0.5,
            "official_evidence_f1": 0.25,
            "recall_at_10": 1.0,
            "MRR": 0.5,
        },
        {
            "answer_types": ["none"],
            "mapped_gold_evidence": False,
            "question_category": "unanswerable",
            "relevant_chunk_count": 0,
            "official_answer_f1": 1.0,
            "official_evidence_f1": 1.0,
            "recall_at_10": 0.0,
            "MRR": 0.0,
        },
    ]

    result = _quality_stratification(cases)

    assert result["by_answer_type"]["boolean"]["question_count"] == 1
    assert result["by_answer_type"]["extractive"]["question_count"] == 1
    assert result["by_mapped_gold_evidence"]["mapped"]["retrieval_metric_denominator"] == 1
    assert result["by_mapped_gold_evidence"]["unmapped"]["retrieval_metric_denominator"] == 0
    assert result["by_evidence_scope"]["local"]["question_count"] == 1
    assert result["answer_type_groups_are_multi_label"] is True
