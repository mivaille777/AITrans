import { describe, expect, it } from "vitest"

import type { AgentTraceEvent } from "../../../api/agent"
import type { DurableAgentRunRecord } from "../../../api/agent-runtime"
import { deriveAgentWorkspaceState } from "./agent-workspace-state"

function event(
  sequence: number,
  eventType: AgentTraceEvent["event_type"],
  payload: Record<string, unknown> = {},
): AgentTraceEvent {
  return {
    sequence,
    event_type: eventType,
    timestamp: "2026-08-27T00:00:00Z",
    run_id: "run-react",
    trace_id: "trace-react",
    elapsed_ms: sequence * 10,
    payload,
  }
}

describe("ReAct workspace activity projection", () => {
  it("projects adaptive decisions and observations into user-visible activity", () => {
    const state = deriveAgentWorkspaceState({
      trace: null,
      pending: true,
      liveEvents: [
        event(0, "react_started", {
          max_iterations: 6,
          max_tool_calls: 4,
        }),
        event(1, "decision_ready", {
          iteration: 1,
          kind: "tool",
          tool_name: "search_knowledge_base",
          action_summary: "Search the knowledge base for supporting evidence.",
        }),
        event(2, "observation_ready", {
          observation_id: "obs-1",
          iteration: 1,
          tool_name: "search_knowledge_base",
          success: true,
          summary_chars: 180,
          evidence_count: 3,
          citation_count: 3,
        }),
        event(3, "decision_ready", {
          iteration: 2,
          kind: "final",
          action_summary: "Enough evidence is available to answer.",
        }),
      ],
    })

    expect(state.phase).toBe("running")
    expect(state.runId).toBe("run-react")
    expect(state.activities.map((item) => item.label)).toEqual([
      "ReAct loop started",
      "Decision #1: search_knowledge_base",
      "Observation #1: search_knowledge_base",
      "Decision #2: finish",
    ])
    expect(state.activities[2].detail).toContain("3 evidence")
    expect(state.activities[2].detail).toContain("3 citations")
  })

  it("never uses hidden reasoning fields as visible decision copy", () => {
    const hiddenReasoning = "PRIVATE_CHAIN_OF_THOUGHT_SHOULD_NOT_RENDER"
    const state = deriveAgentWorkspaceState({
      trace: null,
      pending: true,
      liveEvents: [
        event(0, "decision_ready", {
          iteration: 1,
          kind: "tool",
          tool_name: "inspect_reading_context",
          action_summary: "Inspect the current reading context.",
          thought: hiddenReasoning,
          reasoning: hiddenReasoning,
        }),
      ],
    })

    expect(state.activities[0].detail).toBe("Inspect the current reading context.")
    expect(state.activities[0].label).toBe("Decision #1: inspect_reading_context")
    expect(state.activities[0].detail).not.toContain(hiddenReasoning)
    expect(state.activities[0].label).not.toContain(hiddenReasoning)
  })

  it("surfaces configured ReAct limits as a warning rather than an execution failure", () => {
    const state = deriveAgentWorkspaceState({
      trace: null,
      pending: true,
      liveEvents: [
        event(0, "react_limit_reached", {
          iteration: 4,
          tool_call_count: 4,
          reason: "tool_call_budget_exhausted",
        }),
      ],
    })

    expect(state.phase).toBe("running")
    expect(state.activities[0].tone).toBe("warning")
    expect(state.activities[0].label).toBe("ReAct budget reached")
    expect(state.activities[0].detail).toContain("tool_call_budget_exhausted")
    expect(state.activities[0].detail).toContain("4 tool calls")
  })

  it("makes knowledge routing and evidence sufficiency visible in the runtime timeline", () => {
    const state = deriveAgentWorkspaceState({
      trace: null,
      pending: false,
      liveEvents: [
        event(0, "knowledge_decision", {
          mode: "auto",
          should_retrieve: true,
          reason_code: "document_grounding_required",
          scope_strategy: "attached_document",
        }),
        event(1, "knowledge_scope_resolved", {
          strategy: "attached_document",
          document_count: 1,
          research_source_count: 0,
        }),
        event(2, "rag_query_started", { retrieval_strategy: "hybrid" }),
        event(3, "rag_rerank_completed", { final_count: 6, rerank_ms: 12 }),
        event(4, "evidence_sufficiency", {
          sufficient: true,
          reason: "evidence_sufficient",
          missing_information: [],
          search_count: 1,
        }),
      ],
    })

    expect(state.activities.map((item) => item.label)).toEqual([
      "Knowledge decision",
      "Knowledge scope",
      "RAG retrieval",
      "Evidence reranked",
      "Evidence ready",
    ])
    expect(state.activities[0].detail).toContain("Auto · retrieval required")
    expect(state.activities[1].detail).toContain("Current document")
    expect(state.activities[4].detail).toContain("Evidence is sufficient")
  })

  it("explains why knowledge retrieval was skipped", () => {
    const state = deriveAgentWorkspaceState({
      trace: null,
      pending: false,
      liveEvents: [
        event(0, "knowledge_skipped", {
          reason_code: "current_context_sufficient",
          scope_strategy: "attached_document",
        }),
      ],
    })

    expect(state.activities[0].label).toBe("Knowledge skipped")
    expect(state.activities[0].detail).toBe("Reason: current_context_sufficient")
  })
})


function durableRun(status: DurableAgentRunRecord["status"]): DurableAgentRunRecord {
  return {
    task_id: "task-durable",
    run_id: "run-durable",
    trace_id: "trace-durable",
    runtime_profile: "long_task",
    status,
    created_at: "2026-09-22T00:00:00Z",
    updated_at: "2026-09-22T00:00:01Z",
    started_at: null,
    finished_at: null,
    graph_version: "",
    state_schema_version: 0,
    checkpoint_id: "",
    budget_used_ms: 0,
  }
}

describe("durable runtime phase projection", () => {
  it.each([
    ["queued", "queued"],
    ["running", "running"],
    ["pause_requested", "pausing"],
    ["paused", "paused"],
    ["recovering", "recovering"],
    ["waiting", "waiting"],
    ["completed", "completed"],
    ["failed", "failed"],
    ["cancelled", "cancelled"],
  ] as const)("maps %s to %s from the authoritative run store", (status, phase) => {
    const state = deriveAgentWorkspaceState({
      trace: null,
      durableRun: durableRun(status),
      pending: false,
    })
    expect(state.phase).toBe(phase)
    expect(state.runId).toBe("run-durable")
    expect(state.traceId).toBe("trace-durable")
  })
})
