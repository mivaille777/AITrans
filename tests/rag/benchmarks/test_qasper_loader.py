from __future__ import annotations

import hashlib
import io
import json
import tarfile

from backend.rag.benchmarks.qasper import loader
from backend.rag.benchmarks.qasper.loader import download_qasper_split, load_qasper

PARAGRAPH_ONE = "The proposed model combines retrieval with generation."
PARAGRAPH_TWO = "The evaluation uses three public datasets."


def _raw_qasper() -> dict:
    return {
        "paper-1": {
            "title": "A Test Paper",
            "abstract": "We study evidence grounded question answering.",
            "full_text": [
                {
                    "section_name": "Introduction",
                    "paragraphs": [PARAGRAPH_ONE, PARAGRAPH_TWO],
                },
                {"section_name": "Results", "paragraphs": ["The score improved by 4%."]},
            ],
            "qas": [
                {
                    "question_id": "q-1",
                    "question": "What does the model combine?",
                    "answers": [
                        {
                            "annotation_id": "a-1",
                            "answer": {
                                "extractive_spans": ["retrieval with generation"],
                                "free_form_answer": "",
                                "yes_no": None,
                                "unanswerable": False,
                            },
                            "evidence": [PARAGRAPH_ONE],
                            "highlighted_evidence": ["retrieval with generation"],
                        },
                        {
                            "annotation_id": "a-2",
                            "answer": {
                                "extractive_spans": [],
                                "free_form_answer": "",
                                "yes_no": None,
                                "unanswerable": True,
                            },
                            "evidence": [],
                            "highlighted_evidence": [],
                        },
                    ],
                },
                {
                    "question_id": "q-2",
                    "question": "Did the score improve?",
                    "answers": [
                        {
                            "annotation_id": "a-3",
                            "answer": {
                                "extractive_spans": [],
                                "free_form_answer": "",
                                "yes_no": False,
                                "unanswerable": False,
                            },
                            "evidence": [PARAGRAPH_TWO],
                            "highlighted_evidence": [],
                        }
                    ],
                },
            ],
        }
    }


def test_loader_keeps_all_answer_types_and_stable_paragraph_ids(tmp_path) -> None:
    raw_path = tmp_path / "qasper-dev-v0.3.json"
    raw_path.write_text(json.dumps(_raw_qasper()), encoding="utf-8")

    dataset = load_qasper(raw_path, split="validation")

    paper = dataset.papers["paper-1"]
    assert dataset.split == "validation"
    assert len(dataset.questions) == 2
    assert len(dataset.questions[0].answers) == 2
    assert dataset.questions[0].answers[0].answer_type == "extractive"
    assert dataset.questions[0].answers[0].answer_text == "retrieval with generation"
    assert dataset.questions[0].answers[0].highlighted_evidence == (
        "retrieval with generation",
    )
    assert dataset.questions[0].answers[1].answer_text == "Unanswerable"
    assert dataset.questions[1].answers[0].answer_type == "boolean"
    assert dataset.questions[1].answers[0].answer_text == "No"
    assert [item.paragraph_id for item in paper.paragraphs] == [
        "qasper:validation:paper-1:p0",
        "qasper:validation:paper-1:p1",
        "qasper:validation:paper-1:p2",
        "qasper:validation:paper-1:p3",
    ]


def test_official_archive_extraction_is_cached_and_checksummed(tmp_path, monkeypatch) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    archive_path = raw_root / "qasper-train-dev-v0.3.tgz"
    payload = json.dumps(_raw_qasper()).encode("utf-8")
    with tarfile.open(archive_path, mode="w:gz") as archive:
        member = tarfile.TarInfo("release/qasper-dev-v0.3.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    target = download_qasper_split(
        "validation", raw_root, manifest_directory=tmp_path / "manifests"
    )
    assert json.loads(target.read_text(encoding="utf-8")) == _raw_qasper()
    manifest = json.loads(
        (tmp_path / "manifests" / "qasper-validation-v0.3.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["split"] == "validation"
    monkeypatch.setattr(
        loader,
        "_download_archive",
        lambda _path: (_ for _ in ()).throw(AssertionError("should reuse local data")),
    )
    assert download_qasper_split("validation", raw_root) == target
