from __future__ import annotations

import json

from backend.rag.benchmarks.qasper.adapter import adapt_qasper_paper
from backend.rag.benchmarks.qasper.loader import load_qasper


def test_adapter_preserves_sections_paragraph_offsets_and_provenance(tmp_path) -> None:
    raw = {
        "paper-x": {
            "title": "Structured paper",
            "abstract": "A compact abstract paragraph.",
            "full_text": [
                {
                    "section_name": "Methods",
                    "paragraphs": ["First method paragraph.", "Second method paragraph."],
                },
                {"section_name": "Results", "paragraphs": ["A measured result."]},
            ],
            "qas": [],
        }
    }
    raw_path = tmp_path / "paper.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    dataset = load_qasper(raw_path)

    adapted = adapt_qasper_paper(dataset.papers["paper-x"], split=dataset.split)

    document = adapted.document
    assert document.document.document_id == "qasper:validation:paper-x"
    assert document.document.source_uri == "qasper://validation/paper-x"
    assert [section.heading for section in document.sections] == [
        "Abstract",
        "Methods",
        "Results",
    ]
    assert len(adapted.paragraphs) == 4
    for paragraph in adapted.paragraphs:
        assert document.text[paragraph.start_char : paragraph.end_char] == paragraph.text
    assert document.sections[1].text == "First method paragraph.\n\nSecond method paragraph."
