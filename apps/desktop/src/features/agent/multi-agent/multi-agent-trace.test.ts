import { describe, expect, it } from "vitest"

import type { MultiAgentRunTrace } from "../../../api/agent-multi-agent"
import { deriveMultiAgentNodeStates } from "./multi-agent-trace"

const trace: MultiAgentRunTrace = {
  run_id: "multi-run-1",
  trace_id: "multi-trace-1",
  total_duration_ms: 20,
  plan: [{ agent: "research" }, { agent: "reading" }],
  results: [],
  context: {
    knowledge_context_chars: 120,
    citation_count: 2,
    citations: [],
    memory_keys: ["knowledge_query"],
    intermediate_agents: ["research", "reading"],
  },
  events: [
    {
      sequence: 0,
      event_type: "supervisor_started",
      actor: "supervisor",
      status: "running",
      timestamp: "2026-09-09T00:00:00Z",
      elapsed_ms: 0,
      payload: {},
    },
    {
      sequence: 1,
      event_type: "supervisor_planned",
      actor: "supervisor",
      status: "complete",
      timestamp: "2026-09-09T00:00:00Z",
      elapsed_ms: 1,
      payload: {},
    },
    {
      sequence: 2,
      event_type: "knowledge_retrieved",
      actor: "knowledge",
      status: "complete",
      timestamp: "2026-09-09T00:00:00Z",
      elapsed_ms: 8,
      payload: {},
    },
    {
      sequence: 3,
      event_type: "shared_context_ready",
      actor: "shared_context",
      status: "complete",
      timestamp: "2026-09-09T00:00:00Z",
      elapsed_ms: 9,
      payload: {},
    },
    {
      sequence: 4,
      event_type: "agent_completed",
      actor: "research",
      status: "complete",
      timestamp: "2026-09-09T00:00:00Z",
      elapsed_ms: 14,
      payload: {},
    },
    {
      sequence: 5,
      event_type: "agent_started",
      actor: "reading",
      status: "running",
      timestamp: "2026-09-09T00:00:00Z",
      elapsed_ms: 15,
      payload: {},
    },
  ],
}

describe("deriveMultiAgentNodeStates", () => {
  it("maps runtime actors to graph node states and marks unplanned specialists skipped", () => {
    const states = Object.fromEntries(
      deriveMultiAgentNodeStates(trace).map((node) => [node.id, node]),
    )

    expect(states.supervisor.status).toBe("complete")
    expect(states.knowledge.status).toBe("complete")
    expect(states.shared_context.status).toBe("complete")
    expect(states.research.status).toBe("complete")
    expect(states.reading.status).toBe("running")
    expect(states.translation.status).toBe("skipped")
  })
})
