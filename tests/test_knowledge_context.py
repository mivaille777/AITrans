from __future__ import annotations

import json

from app.ai.knowledge_context import (
    compact_knowledge_context,
    knowledge_context_diagnostics,
    knowledge_context_json,
)


def _large_context() -> dict[str, object]:
    return {
        "canvas": {"board_id": "board-1", "board_name": "large", "scope_label": "Canvas"},
        "cards": [
            {
                "item_id": f"card-{index}",
                "item_type": "evidence",
                "title": f"Card {index}",
                "summary": "x" * 8000,
                "document_id": "doc-1" if index < 10 else "doc-2",
            }
            for index in range(20)
        ],
        "relations": [
            {
                "relation_id": f"relation-{index}",
                "source_item_id": f"card-{index}",
                "source_title": f"Card {index}",
                "target_item_id": f"card-{index + 1}",
                "target_title": f"Card {index + 1}",
                "relation_type": "supports",
                "label": f"edge {index}",
                "origin": "manual",
                "confidence": None,
            }
            for index in range(6)
        ],
    }


def test_compaction_preserves_relations_before_large_card_summaries() -> None:
    context = _large_context()

    compact = compact_knowledge_context(context, max_chars=5000)
    assert [item["relation_id"] for item in compact["relations"]] == [
        f"relation-{index}" for index in range(6)
    ]
    assert len(compact["cards"]) < len(context["cards"])

    serialized = knowledge_context_json(context, max_chars=5000)
    assert len(serialized) <= 5000
    decoded = json.loads(serialized)
    assert decoded["relations"] == compact["relations"]


def test_diagnostics_report_safe_counts_stage_visibility_and_compaction() -> None:
    diagnostics = knowledge_context_diagnostics(_large_context())

    assert diagnostics["binding"] == "knowledge_canvas"
    assert diagnostics["canvas"] == {
        "board_id": "board-1",
        "board_name": "large",
        "scope_label": "Canvas",
    }
    assert diagnostics["attached"] == {
        "cards": 20,
        "relations": 6,
        "documents": 2,
    }
    assert diagnostics["visibility"] == {
        "planner": True,
        "react": True,
        "synthesis": True,
    }
    assert diagnostics["relation_trust"] == "organizational_context_not_factual_evidence"

    planner = diagnostics["stages"]["planner"]
    synthesis = diagnostics["stages"]["synthesis"]
    assert planner["max_chars"] == 7000
    assert synthesis["max_chars"] == 9000
    assert planner["relations_included"] == 6
    assert synthesis["relations_included"] == 6
    assert planner["truncated"] is True
    assert planner["card_summaries_compacted"] > 0
    assert synthesis["used_chars"] <= synthesis["max_chars"]
