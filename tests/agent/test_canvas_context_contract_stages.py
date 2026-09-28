from __future__ import annotations

import json

from app.ai.chat.service import build_chat_prompt
from backend.services.agent_planner_service import AgentPlannerService
from backend.services.agent_react_decision_service import AgentReActDecisionService
from backend.services.companion_chat_service import CompanionChatService


def _knowledge_context() -> dict[str, object]:
    return {
        "canvas": {
            "board_id": "board-stage",
            "board_name": "Stage contract",
            "scope_label": "Canvas",
        },
        "cards": [
            {
                "item_id": "card-a",
                "item_type": "insight",
                "title": "Insight A",
                "summary": "Bounded mechanism-guided refinement.",
                "document_id": "doc-1",
            },
            {
                "item_id": "card-b",
                "item_type": "evidence",
                "title": "Evidence B",
                "summary": "Evidence from the indexed paper.",
                "document_id": "doc-1",
            },
        ],
        "relations": [
            {
                "relation_id": "relation-stage-1",
                "source_item_id": "card-a",
                "source_title": "Insight A",
                "target_item_id": "card-b",
                "target_title": "Evidence B",
                "relation_type": "supports",
                "label": "manual contract edge",
                "origin": "manual",
                "confidence": None,
            }
        ],
    }


def _shared_payload() -> dict[str, object]:
    return {
        "user_message": "List the explicit Canvas relations.",
        "source_text": "",
        "translated_text": "",
        "resource_url": "",
        "resource_title": "",
        "section_heading": "",
        "context_before": "",
        "context_after": "",
        "source_kind": "knowledge_document",
        "history": (),
        "knowledge_context": _knowledge_context(),
    }


def test_planner_prompt_receives_first_class_canvas_context() -> None:
    planner = AgentPlannerService()
    payload = json.loads(planner._planner_payload(tools=(), **_shared_payload()))

    assert payload["selected_context"]["source_text"] == ""
    assert payload["knowledge_context"]["canvas"]["board_id"] == "board-stage"
    assert payload["knowledge_context"]["relations"][0]["relation_id"] == "relation-stage-1"
    assert payload["runtime_policy"]["knowledge_relation_trust"] == (
        "organizational_context_not_factual_evidence"
    )


def test_react_prompt_receives_first_class_canvas_context() -> None:
    service = AgentReActDecisionService()
    payload = json.loads(
        service._payload(
            iteration=1,
            tools=(),
            observations=(),
            remaining_tool_calls=2,
            remaining_knowledge_searches=1,
            **_shared_payload(),
        )
    )

    assert payload["selected_context"]["source_text"] == ""
    assert payload["knowledge_context"]["canvas"]["board_name"] == "Stage contract"
    relation = payload["knowledge_context"]["relations"][0]
    assert relation["relation_type"] == "supports"
    assert relation["origin"] == "manual"
    assert payload["runtime_policy"]["knowledge_relation_trust"] == (
        "organizational_context_not_factual_evidence"
    )


def test_companion_prompt_keeps_canvas_and_bounded_relative_workspace_manifest() -> None:
    request = CompanionChatService._build_request(
        session_id="canvas-stage",
        context_mode="general",
        filesystem_workspace_files=[
            {"relative_path": "input/data.csv", "size_bytes": 42},
            {"relative_path": "C:/private/key.txt", "size_bytes": 7},
            {"relative_path": "../outside.txt", "size_bytes": 9},
        ],
        **_shared_payload(),
    )
    _prefix, serialized = build_chat_prompt(request).split("\n\n", 1)
    payload = json.loads(serialized)

    assert payload["knowledge_context"]["canvas"]["board_id"] == "board-stage"
    assert payload["filesystem_workspace_files"] == [
        {"relative_path": "input/data.csv", "size_bytes": 42}
    ]
    assert payload["reading_context"] is None


def test_companion_prompt_keeps_valid_json_when_workspace_manifest_is_large() -> None:
    request = CompanionChatService._build_request(
        session_id="canvas-large-manifest",
        context_mode="general",
        filesystem_workspace_files=[
            {"relative_path": f"input/{index:02d}-{'x' * 150}.csv", "size_bytes": index}
            for index in range(64)
        ],
        **_shared_payload(),
    )
    _prefix, serialized = build_chat_prompt(request).split("\n\n", 1)
    files = json.loads(serialized)["filesystem_workspace_files"]

    assert 1 < len(files) < 64
    assert len(json.dumps(files, ensure_ascii=False)) <= 2_400
    assert files[0]["relative_path"].startswith("input/00-")
