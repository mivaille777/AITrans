from __future__ import annotations

import json
from pathlib import Path

from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector
from tests.multi_agent.scheduler_support import plan, success

_FIXTURE = Path(__file__).parent / "fixtures" / "lg00-baseline.json"


def test_lg00_plan_result_and_event_contract_remain_stable() -> None:
    baseline = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert plan().model_dump(mode="json") == baseline["task_plan"]
    assert success("a").result.model_dump(
        mode="json", exclude={"started_at", "finished_at"}
    ) == baseline["task_result"]

    collector = MultiAgentTraceCollector(run_id="lg00-run", trace_id="lg00-trace")
    for event_type, status, attempt in (
        ("task_planned", "pending", 0),
        ("task_started", "running", 1),
        ("task_completed", "succeeded", 1),
    ):
        payload = {"task_id": "a", "plan_revision": 1}
        if attempt:
            payload["attempt"] = attempt
        collector.emit(event_type, actor="document", status=status, payload=payload)

    actual = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "actor": event.actor,
            "status": event.status,
            "payload": {
                key: value for key, value in event.payload.items() if key != "timestamp"
            },
        }
        for event in collector.events
    ]
    assert actual == baseline["event_contract"]
