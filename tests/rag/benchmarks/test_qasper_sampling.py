from __future__ import annotations

import hashlib
import json

import pytest

from backend.rag.benchmarks.qasper.loader import load_qasper
from backend.rag.benchmarks.qasper.sampling import (
    read_question_ids_file,
    sample_qasper_dataset,
)


def _dataset(tmp_path):
    raw_path = tmp_path / "qasper.json"
    papers = {}
    for index in range(3):
        paper_id = f"paper-{index}"
        papers[paper_id] = {
            "title": paper_id,
            "abstract": "",
            "full_text": [],
            "qas": [
                {
                    "question_id": f"q-{index}-{question_index}",
                    "question": "Question?",
                    "answers": [
                        {
                            "answer": {
                                "extractive_spans": [],
                                "free_form_answer": "",
                                "yes_no": None,
                                "unanswerable": True,
                            },
                            "evidence": [],
                            "highlighted_evidence": [],
                        }
                    ],
                }
                for question_index in range(4)
            ],
        }
    raw_path.write_text(json.dumps(papers), encoding="utf-8")
    return load_qasper(raw_path)


def test_explicit_question_ids_preserve_source_order_and_restrict_papers(tmp_path) -> None:
    dataset = _dataset(tmp_path)
    selected = sample_qasper_dataset(
        dataset,
        limit=2,
        seed=1,
        question_ids=("q-2-1", "q-0-2"),
    )

    assert [item.question_id for item in selected.questions] == ["q-0-2", "q-2-1"]
    assert set(selected.papers) == {"paper-0", "paper-2"}
    assert selected.papers["paper-0"].question_ids == ("q-0-2",)


@pytest.mark.parametrize(
    ("question_ids", "limit", "message"),
    [
        (("q-0-0", "q-0-0"), None, "unique"),
        (("missing",), None, "absent from the selected"),
        (("q-0-0",), 2, "expected 2"),
    ],
)
def test_explicit_question_ids_reject_duplicates_unknown_ids_and_count_mismatch(
    tmp_path,
    question_ids,
    limit,
    message,
) -> None:
    dataset = _dataset(tmp_path)
    with pytest.raises(ValueError, match=message):
        sample_qasper_dataset(
            dataset,
            limit=limit,
            seed=42,
            question_ids=question_ids,
        )


def test_question_id_file_is_hashed_and_duplicate_ids_are_rejected(tmp_path) -> None:
    path = tmp_path / "ids.txt"
    path.write_bytes(b"q1\nq2\n")
    assert read_question_ids_file(path) == (("q1", "q2"), hashlib.sha256(b"q1\nq2\n").hexdigest())

    path.write_text("q1\nq1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate IDs"):
        read_question_ids_file(path)
