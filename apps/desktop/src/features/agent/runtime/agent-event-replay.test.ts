import { describe, expect, it } from "vitest"

import type { AgentTraceEvent } from "../../../api/agent"
import { latestTaskEvent, mergeAgentEvents } from "./agent-event-replay"

function event(sequence: number, eventType: AgentTraceEvent["event_type"], status: string): AgentTraceEvent {
  return {
    sequence,
    event_type: eventType,
    timestamp: "2026-09-17T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: sequence,
    payload: { task_id: "document-1", status },
  }
}

describe("agent event replay", () => {
  it("deduplicates replayed sequences and accepts the authoritative replacement", () => {
    const merged = mergeAgentEvents(
      [event(1, "task_started", "running"), event(2, "task_progress", "running")],
      [event(2, "task_progress", "running"), event(3, "task_completed", "succeeded")],
      "run-1",
    )
    expect(merged.map((item) => item.sequence)).toEqual([1, 2, 3])
  })

  it("does not regress a terminal task when a late running event is replayed", () => {
    const events = mergeAgentEvents(
      [event(5, "task_completed", "succeeded")],
      [event(6, "task_progress", "running")],
      "run-1",
    )
    expect(latestTaskEvent(events, "document-1")?.event_type).toBe("task_completed")
  })

  it("ignores events from another run", () => {
    const other = { ...event(2, "task_failed", "failed"), run_id: "run-2" }
    expect(mergeAgentEvents([event(1, "task_started", "running")], [other], "run-1")).toHaveLength(1)
  })
})
