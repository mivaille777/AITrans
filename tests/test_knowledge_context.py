from __future__ import annotations

import json

from app.ai.knowledge_context import compact_knowledge_context, knowledge_context_json


def test_compaction_preserves_relations_before_large_card_summaries() -> None:
    context = {
        "canvas": {"board_id": "board-1", "board_name": "large", "scope_label": "Canvas"},
        "cards": [
            {
                "item_id": f"card-{index}",
                "item_type": "evidence",
                "title": f"Card {index}",
                "summary": "x" * 8000,
                "document_id": "doc-1",
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

    compact = compact_knowledge_context(context, max_chars=5000)
    assert [item["relation_id"] for item in compact["relations"]] == [
        f"relation-{index}" for index in range(6)
    ]
    assert len(compact["cards"]) < len(context["cards"])

    serialized = knowledge_context_json(context, max_chars=5000)
    assert len(serialized) <= 5000
    decoded = json.loads(serialized)
    assert decoded["relations"] == compact["relations"]
