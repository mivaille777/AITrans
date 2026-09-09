import { describe, expect, it } from "vitest"

import type { AgentTraceEvent } from "../../../api/agent"
import { deriveMultiAgentNodeStates, isMultiAgentTraceEvent } from "./multi-agent-trace"

const events: AgentTraceEvent[] = [
  {
    sequence: 0,
    event_type: "agent_start",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 0,
    payload: {},
  },
  {
    sequence: 1,
    event_type: "multi_agent_started",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 1,
    payload: { actor: "supervisor", status: "running" },
  },
  {
    sequence: 2,
    event_type: "multi_agent_plan_ready",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 2,
    payload: {
      actor: "supervisor",
      status: "complete",
      agents: ["research", "reading"],
    },
  },
  {
    sequence: 3,
    event_type: "multi_agent_knowledge_ready",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 8,
    payload: {
      actor: "knowledge",
      status: "complete",
      citation_count: 2,
      context_chars: 120,
    },
  },
  {
    sequence: 4,
    event_type: "multi_agent_context_ready",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 9,
    payload: { actor: "shared_context", status: "complete" },
  },
  {
    sequence: 5,
    event_type: "multi_agent_specialist_completed",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 14,
    payload: { actor: "research", status: "complete" },
  },
  {
    sequence: 6,
    event_type: "multi_agent_specialist_started",
    timestamp: "2026-09-09T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 15,
    payload: { actor: "reading", status: "running" },
  },
]

describe("deriveMultiAgentNodeStates", () => {
  it("maps primary runtime events to graph node states and marks unplanned specialists skipped", () => {
    const states = Object.fromEntries(
      deriveMultiAgentNodeStates(events).map((node) => [node.id, node]),
    )

    expect(states.supervisor.status).toBe("complete")
    expect(states.knowledge.status).toBe("complete")
    expect(states.shared_context.status).toBe("complete")
    expect(states.research.status).toBe("complete")
    expect(states.reading.status).toBe("running")
    expect(states.translation.status).toBe("skipped")
  })

  it("filters only unified multi-agent lifecycle events", () => {
    expect(events.filter(isMultiAgentTraceEvent)).toHaveLength(6)
  })
})
