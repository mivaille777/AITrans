import pytest

from backend.rag.evaluation import evaluate_rag
from backend.rag.evaluation_dataset import (
    RagClaimPrediction,
    RagEvaluationCase,
    RagEvaluationPrediction,
)
from backend.rag.evaluation_protocol import ClaimAssessment


def test_hand_calculated_denominators_complete_sets_and_grade_zero():
    case = RagEvaluationCase(
        case_id="c", query="q", relevant_chunk_ids=["a", "b"], relevance_grades={"noise": 0},
        evidence_sets=[["a", "b"], ["alternative"]], expected_scope_document_ids=["d"],
        gold_document_ids=["d"],
    )
    prediction = RagEvaluationPrediction(case_id="c", ranked_chunk_ids=["noise", "a"],
                                        chunk_document_ids={"a": "d", "b": "d", "noise": "d"})
    result = evaluate_rag([case], [prediction])
    assert result.retrieval.mrr == .5
    assert result.retrieval.recall_at_5 == .5
    assert result.production["precision_at_5"]["value"] == .2
    assert result.production["evidence_recall_at_1"]["value"] == 0
    assert result.production["complete_evidence_at_5"]["value"] == 0
    assert result.production["document_recall_at_5"]["value"] == 1
    alternative = RagEvaluationPrediction(case_id="c", ranked_chunk_ids=["alternative"], chunk_document_ids={"alternative": "d"})
    assert evaluate_rag([case], [alternative]).production["complete_evidence_at_1"]["value"] == 1


def test_self_report_is_ignored_and_independent_assessment_is_required():
    case = RagEvaluationCase(case_id="c", query="q")
    prediction = RagEvaluationPrediction(case_id="c", claims=[RagClaimPrediction(claim_id="x", supported=True)])
    assert evaluate_rag([case], [prediction]).production["independent_answer"]["n"] == 0
    label = ClaimAssessment(case_id="c", claim_id="x", supported=False, citation_correct=False,
                            method="human", assessor="reviewer", review_id="blind-1")
    result = evaluate_rag([case], [prediction], assessments=[label])
    assert result.citations.unsupported_claim_rate == 1
    assert result.production["independent_answer"]["faithfulness"] == 0
    assert result.production["evidence_recall_at_5"]["n"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_rag([case], [prediction, prediction])


def test_relevant_but_insufficient_schema_preserves_legacy_rules():
    case = RagEvaluationCase(case_id="c", query="q", no_answer=True, categories=["no_answer"],
                             answerability="relevant_insufficient", relevant_chunk_ids=["a"])
    assert case.graded_relevance == {"a": 1}
