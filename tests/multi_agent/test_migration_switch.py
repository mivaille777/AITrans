from __future__ import annotations

import pytest

from backend.agent_core.orchestration.migration import (
    build_migration_bridge,
    resolve_multi_agent_engine,
    resolve_multi_agent_rollout,
)
from backend.agent_core.state import AgentState
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute


class _Service:
    planner = object()


class _Orchestrator:
    def route(self, user_input, runtime_context, *, mode):
        del runtime_context, mode
        return OrchestrationRoute(
            lane=(
                OrchestrationLane.WORKFLOW
                if "workflow" in user_input
                else OrchestrationLane.SINGLE
            ),
            reason_code="rollout-test",
        )


def test_migration_engine_defaults_to_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AITRANS_MULTI_AGENT_ENGINE", raising=False)
    assert resolve_multi_agent_engine() == "typed"


def test_migration_engine_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="typed, legacy, off"):
        resolve_multi_agent_engine("surprise")


def test_rollout_defaults_to_single_and_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AITRANS_MULTI_AGENT_ROLLOUT", raising=False)
    assert resolve_multi_agent_rollout() == "single"
    with pytest.raises(ValueError, match="simple, single, workflow"):
        resolve_multi_agent_rollout("surprise")


def test_typed_engine_keeps_new_orchestrator() -> None:
    orchestrator = _Orchestrator()
    bridge = build_migration_bridge(_Service(), orchestrator=orchestrator, engine="typed")  # type: ignore[arg-type]
    assert bridge is not None
    assert bridge.orchestrator is orchestrator


def test_simple_rollout_keeps_canonical_single_agent_path() -> None:
    assert build_migration_bridge(
        _Service(),
        orchestrator=_Orchestrator(),
        engine="typed",
        rollout="simple",
    ) is None  # type: ignore[arg-type]


def test_single_rollout_allows_one_specialist_but_not_workflow() -> None:
    bridge = build_migration_bridge(
        _Service(),
        orchestrator=_Orchestrator(),
        engine="typed",
        rollout="single",
    )
    assert bridge is not None
    assert bridge.should_run(AgentState(user_input="single task")) is True
    assert bridge.should_run(AgentState(user_input="workflow task")) is False


def test_workflow_rollout_allows_single_and_workflow_lanes() -> None:
    bridge = build_migration_bridge(
        _Service(),
        orchestrator=_Orchestrator(),
        engine="typed",
        rollout="workflow",
    )
    assert bridge is not None
    assert bridge.should_run(AgentState(user_input="single task")) is True
    assert bridge.should_run(AgentState(user_input="workflow task")) is True


def test_legacy_engine_keeps_old_collaboration_without_typed_orchestrator() -> None:
    bridge = build_migration_bridge(_Service(), orchestrator=_Orchestrator(), engine="legacy")  # type: ignore[arg-type]
    assert bridge is not None
    assert bridge.orchestrator is None
    assert bridge.service is not None


def test_off_engine_disables_collaboration_without_removing_canonical_runtime() -> None:
    assert build_migration_bridge(_Service(), orchestrator=_Orchestrator(), engine="off") is None  # type: ignore[arg-type]
