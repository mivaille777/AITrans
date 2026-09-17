from __future__ import annotations

import pytest

from backend.agent_core.orchestration.migration import (
    build_migration_bridge,
    resolve_multi_agent_engine,
)


class _Service:
    planner = object()


class _Orchestrator:
    pass


def test_migration_engine_defaults_to_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AITRANS_MULTI_AGENT_ENGINE", raising=False)
    assert resolve_multi_agent_engine() == "typed"


def test_migration_engine_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="typed, legacy, off"):
        resolve_multi_agent_engine("surprise")


def test_typed_engine_keeps_new_orchestrator() -> None:
    orchestrator = _Orchestrator()
    bridge = build_migration_bridge(_Service(), orchestrator=orchestrator, engine="typed")  # type: ignore[arg-type]
    assert bridge is not None
    assert bridge.orchestrator is orchestrator


def test_legacy_engine_keeps_old_collaboration_without_typed_orchestrator() -> None:
    bridge = build_migration_bridge(_Service(), orchestrator=_Orchestrator(), engine="legacy")  # type: ignore[arg-type]
    assert bridge is not None
    assert bridge.orchestrator is None
    assert bridge.service is not None


def test_off_engine_disables_collaboration_without_removing_canonical_runtime() -> None:
    assert build_migration_bridge(_Service(), orchestrator=_Orchestrator(), engine="off") is None  # type: ignore[arg-type]
