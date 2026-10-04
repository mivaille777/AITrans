import hashlib
import json

import pytest

from backend.rag.evaluation_protocol import ClaimAssessment
from scripts.calibrate_rag_judge import judge, score, selected_claims
from scripts.eval_rag_production import validate_judge_calibration


class Client:
    def __init__(self, output):
        self.output = output

    def complete(self, **kwargs):
        assert "human_label" not in kwargs["user_prompt"]
        return self.output


def test_json_fence_preserves_labels_and_raw_audit():
    raw = '```json\n{"labels":["Entailment"]}\n```'
    labels, original = judge(Client(raw), "reference", [["a", "uses", "b"]])
    assert labels == ["Entailment"]
    assert original == raw


@pytest.mark.parametrize("raw", ['{"labels":[]}', '{"labels":["Maybe"]}',
                                  '{"labels":["Entailment"],"supported":true}'])
def test_invalid_judge_contract_is_rejected(raw):
    with pytest.raises(ValueError):
        judge(Client(raw), "reference", [["a", "uses", "b"]])


def test_errors_remain_in_calibration_denominator():
    metrics = score([{"human_label": "Entailment", "predicted_label": "Entailment"},
                     {"human_label": "Neutral", "error": "timeout"}])
    assert metrics["binary_agreement"] == .5
    assert metrics["errors"] == 1
    assert metrics["qualified"] is False


def test_noisy_context_selection_keeps_questions_disjoint_and_source_labels(tmp_path):
    labels = ["Entailment", "Contradiction", "Neutral"]
    contexts = {str(i): {"reference": f"reference {i}"} for i in range(6)}
    answers = [{"id": str(i), "claude2_response_kg": [
        {"triplet": [str(i), "relation", label], "human_label": label} for label in labels
    ]} for i in range(6)]
    (tmp_path / "msmarco-contexts.json").write_text(json.dumps(contexts))
    (tmp_path / "msmarco_model_answers.json").write_text(json.dumps(answers))
    splits = selected_claims(tmp_path, dataset="msmarco", seed=17, claims_per_label=1,
                             excluded_case_ids={"0"})
    ids = [{x["case_id"] for x in items} for items in splits.values()]
    assert not ids[0].intersection(ids[1]) and "0" not in ids[0].union(ids[1])
    for items in splits.values():
        assert {x["human_label"] for x in items} == set(labels)
        assert all(x["reference"] == contexts[x["case_id"]]["reference"] for x in items)


def test_uncalibrated_judge_cannot_claim_independent_accuracy(tmp_path):
    label = ClaimAssessment(case_id="q", claim_id="c", supported=True, citation_correct=True,
        assessor="judge", method="calibrated_judge", review_id="review", calibration_id="claimed")
    with pytest.raises(ValueError, match="qualified calibration"):
        validate_judge_calibration([label], None)
    path = tmp_path / "record.json"
    path.write_text(json.dumps({"qualified": False, "N": 90, "errors": 0,
                                "binary_agreement": .9, "supported_precision": .84}))
    with pytest.raises(ValueError, match="qualification criteria"):
        validate_judge_calibration([label], path)


def test_calibrated_labels_bind_the_actual_record(tmp_path):
    path = tmp_path / "record.json"
    path.write_text(json.dumps({"qualified": True, "N": 90, "errors": 0,
                                "binary_agreement": .95, "supported_precision": .95}))
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    label = ClaimAssessment(case_id="q", claim_id="c", supported=True, citation_correct=True,
        assessor="judge", method="calibrated_judge", review_id="review", calibration_id=fingerprint)
    assert validate_judge_calibration([label], path) == fingerprint
    with pytest.raises(ValueError, match="record SHA256"):
        validate_judge_calibration([label.model_copy(update={"calibration_id": "other"})], path)
