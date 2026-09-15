from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.services.agent_trace_store_service import StoredAgentEvent, StoredAgentRun


@dataclass(frozen=True, slots=True)
class AgentRegressionFixtureCase:
    case_id: str
    run: StoredAgentRun
    events: tuple[StoredAgentEvent, ...]


@dataclass(frozen=True, slots=True)
class AgentRegressionFixture:
    cases: tuple[AgentRegressionFixtureCase, ...]

    def get_case(self, case_id: str) -> AgentRegressionFixtureCase | None:
        candidate = str(case_id or "").strip()
        return next((item for item in self.cases if item.case_id == candidate), None)

    def get_run(self, case_id: str) -> StoredAgentRun | None:
        item = self.get_case(case_id)
        return item.run if item is not None else None

    def get_events(self, run: StoredAgentRun) -> tuple[StoredAgentEvent, ...]:
        item = next((case for case in self.cases if case.run.run_id == run.run_id), None)
        return item.events if item is not None else ()


def _parse_event(case_id: str, raw: object, index: int) -> StoredAgentEvent:
    if not isinstance(raw, dict):
        raise ValueError(f"Regression fixture {case_id!r} event {index} must be an object.")
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError(
            f"Regression fixture {case_id!r} event {index} payload must be an object."
        )
    return StoredAgentEvent(
        sequence=int(raw.get("sequence", index)),
        event_type=str(raw.get("event_type", "") or "").strip(),
        timestamp=str(raw.get("timestamp", "") or "").strip(),
        elapsed_ms=max(0, int(raw.get("elapsed_ms", 0) or 0)),
        payload=dict(payload),
    )


def load_regression_fixture(path: str | Path) -> AgentRegressionFixture:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Regression fixture root must be an object.")
    raw_cases = payload.get("cases", [])
    if not isinstance(raw_cases, list):
        raise ValueError("Regression fixture 'cases' must be a list.")

    cases: list[AgentRegressionFixtureCase] = []
    seen_case_ids: set[str] = set()
    seen_run_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Regression fixture case {index} must be an object.")
        case_id = str(raw_case.get("case_id", "") or "").strip()
        if not case_id:
            raise ValueError(f"Regression fixture case {index} is missing case_id.")
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate regression fixture case_id: {case_id}")
        raw_run = raw_case.get("run", {})
        if not isinstance(raw_run, dict):
            raise ValueError(f"Regression fixture {case_id!r} run must be an object.")
        run = StoredAgentRun(**raw_run)
        if not run.run_id:
            raise ValueError(f"Regression fixture {case_id!r} run_id cannot be empty.")
        if run.run_id in seen_run_ids:
            raise ValueError(f"Duplicate regression fixture run_id: {run.run_id}")

        raw_events = raw_case.get("events", [])
        if not isinstance(raw_events, list):
            raise ValueError(f"Regression fixture {case_id!r} events must be a list.")
        events = tuple(
            _parse_event(case_id, raw_event, event_index)
            for event_index, raw_event in enumerate(raw_events)
        )
        expected_sequences = tuple(range(len(events)))
        actual_sequences = tuple(event.sequence for event in events)
        if actual_sequences != expected_sequences:
            raise ValueError(
                f"Regression fixture {case_id!r} event sequences must be contiguous from zero."
            )
        if run.event_count != len(events):
            raise ValueError(
                f"Regression fixture {case_id!r} event_count={run.event_count} "
                f"does not match events={len(events)}."
            )

        seen_case_ids.add(case_id)
        seen_run_ids.add(run.run_id)
        cases.append(AgentRegressionFixtureCase(case_id=case_id, run=run, events=events))

    return AgentRegressionFixture(cases=tuple(cases))


__all__ = [
    "AgentRegressionFixture",
    "AgentRegressionFixtureCase",
    "load_regression_fixture",
]
