from __future__ import annotations

import pytest

from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    CURRENT_AGENT_STATE_SCHEMA_VERSION,
    AgentState,
    migrate_agent_state_payload,
)


def test_pre_ma03_state_payload_is_upgraded_with_compatibility_marker() -> None:
    payload = AgentState(user_input="legacy").model_dump(mode="json")
    payload.pop("graph_version")
    payload.pop("state_schema_version")
    payload.pop("checkpoint_source_graph_version")

    migrated = migrate_agent_state_payload(payload)

    assert migrated["graph_version"] == CURRENT_AGENT_GRAPH_VERSION
    assert migrated["state_schema_version"] == CURRENT_AGENT_STATE_SCHEMA_VERSION
    assert migrated["checkpoint_source_graph_version"] == "reading-agent-v1"
    assert AgentState.model_validate(migrated).user_input == "legacy"


def test_unknown_graph_or_future_schema_is_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="graph_version"):
        migrate_agent_state_payload({"graph_version": "unknown-v99"})
    with pytest.raises(ValueError, match="schema version"):
        migrate_agent_state_payload(
            {
                "graph_version": CURRENT_AGENT_GRAPH_VERSION,
                "state_schema_version": CURRENT_AGENT_STATE_SCHEMA_VERSION + 1,
            }
        )
