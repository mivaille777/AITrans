from __future__ import annotations

import pytest

from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    CURRENT_AGENT_STATE_SCHEMA_VERSION,
    LEGACY_AGENT_GRAPH_VERSION,
    migrate_agent_state_payload,
)
from backend.models.agent_tools import AgentRunRequest, AgentTraceEvent


def test_pre_ma09_agent_request_still_parses_without_new_fields() -> None:
    request = AgentRunRequest.model_validate(
        {
            "user_message": "Explain the selected paragraph.",
            "source_text": "Legacy selected text.",
            "session_id": "legacy-session",
            "workspace_id": "workspace-a",
        }
    )

    assert request.workflow_action == ""
    assert request.retry_task_id == ""
    assert request.temporary is False
    assert request.user_message == "Explain the selected paragraph."


def test_legacy_multi_agent_trace_event_remains_parseable() -> None:
    event = AgentTraceEvent.model_validate(
        {
            "sequence": 7,
            "event_type": "multi_agent_specialist_completed",
            "timestamp": "2026-09-17T00:00:00Z",
            "run_id": "legacy-run",
            "trace_id": "legacy-trace",
            "payload": {"actor": "ResearchAgent", "status": "completed"},
        }
    )

    assert event.event_type == "multi_agent_specialist_completed"
    assert event.payload["actor"] == "ResearchAgent"


def test_legacy_checkpoint_migration_preserves_business_results() -> None:
    business_result = {
        "tool_name": "save_research_note",
        "effect": "write",
        "data": {"note_id": "existing-note", "operation_id": "op-existing"},
    }
    migrated = migrate_agent_state_payload(
        {
            "run_id": "legacy-run",
            "trace_id": "legacy-trace",
            "user_input": "continue",
            "tool_results": [business_result],
            "browser_context": {"workspace_id": "workspace-a"},
        }
    )

    assert migrated["graph_version"] == CURRENT_AGENT_GRAPH_VERSION
    assert migrated["state_schema_version"] == CURRENT_AGENT_STATE_SCHEMA_VERSION
    assert migrated["checkpoint_source_graph_version"] == LEGACY_AGENT_GRAPH_VERSION
    assert migrated["tool_results"] == [business_result]
    assert migrated["browser_context"] == {"workspace_id": "workspace-a"}


def test_unknown_checkpoint_graph_is_explicitly_rejected_without_mutation() -> None:
    original = {
        "graph_version": "future-unknown-graph",
        "state_schema_version": 1,
        "tool_results": [{"data": {"note_id": "must-survive"}}],
    }

    with pytest.raises(ValueError, match="unsupported Agent graph_version"):
        migrate_agent_state_payload(original)

    assert original["tool_results"][0]["data"]["note_id"] == "must-survive"
