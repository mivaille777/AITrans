import { describe, expect, it } from "vitest"

import type { AgentRunTraceResponse, AgentTraceEvent } from "../../api/agent"
import { deriveAgentWorkspaceState } from "./agent-workspace-state"

function event(
  sequence: number,
  event_type: AgentTraceEvent["event_type"],
  payload: Record<string, unknown>,
): AgentTraceEvent {
  return {
    sequence,
    event_type,
    timestamp: `2026-08-22T00:00:0${sequence}+00:00`,
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: sequence * 100,
    payload,
  }
}

const trace: AgentRunTraceResponse = {
  run_id: "run-1",
  trace_id: "trace-1",
  session_id: "session-1",
  ui_mode: "translation",
  total_duration_ms: 600,
  run: {
    status: "completed",
    conversation_id: "conversation-1",
    plan: {
      action: "tool",
      tool_name: "translate_selection",
      user_visible_reason: "Translate the current selection.",
      arguments: { target_language: "zh-CN" },
    },
    output_text: "贝叶斯优化",
    provider: "fake",
    model: "stub-model",
    request_id: 7,
    tool_result: null,
    evidence: [],
    citations: [],
  },
  events: [
    event(0, "agent_start", { session_id: "session-1", run_id: "run-1" }),
    event(1, "context_ready", { resource_title: "Control Paper" }),
    event(2, "plan_ready", {
      action: "tool",
      tool_name: "translate_selection",
      user_visible_reason: "Use the bounded translation tool.",
      duration_ms: 48,
    }),
    event(3, "tool_call", { name: "translate_selection" }),
    event(4, "tool_result", {
      tool_name: "translate_selection",
      provider: "fake",
      duration_ms: 125,
    }),
    event(5, "synthesis_ready", { model: "stub-model", duration_ms: 210 }),
    event(6, "agent_end", {
      status: "completed",
      intent: "translate_selection",
      total_duration_ms: 600,
    }),
  ],
}

describe("agent workspace state", () => {
  it("projects reliability trace events and timing metadata", () => {
    const state = deriveAgentWorkspaceState({ trace })

    expect(state.phase).toBe("completed")
    expect(state.uiMode).toBe("translation")
    expect(state.outputText).toBe("贝叶斯优化")
    expect(state.runId).toBe("run-1")
    expect(state.traceId).toBe("trace-1")
    expect(state.totalDurationMs).toBe(600)
    expect(state.activities.map((item) => item.label)).toEqual([
      "Agent started",
      "Context ready",
      "Plan ready: translate_selection",
      "Tool planned: translate_selection",
      "translate_selection completed",
      "Response synthesized",
      "Agent completed",
    ])
    expect(state.activities[2].detail).toContain("48 ms")
    expect(state.activities[4].detail).toContain("125 ms")
  })

  it("surfaces write confirmation as a dedicated workspace phase", () => {
    const state = deriveAgentWorkspaceState({
      trace: {
        ...trace,
        ui_mode: "note",
        run: {
          ...trace.run,
          status: "confirmation_required",
          plan: {
            action: "tool",
            tool_name: "save_research_note",
            user_visible_reason: "Saving changes persistent state.",
            arguments: {},
          },
          output_text: "",
        },
      },
    })

    expect(state.phase).toBe("confirmation_required")
    expect(state.confirmationTool).toBe("save_research_note")
  })

  it("uses live retry events while a new run is pending", () => {
    const liveEvents: AgentTraceEvent[] = [
      event(0, "agent_start", { session_id: "session-1" }),
      event(1, "context_ready", { resource_title: "New Paper" }),
      event(2, "plan_ready", { action: "tool", tool_name: "explain_selection" }),
      event(3, "tool_call", { name: "explain_selection" }),
      event(4, "retry", {
        tool_name: "explain_selection",
        attempt: 2,
        max_attempts: 2,
        reason: "temporary provider failure",
      }),
    ]

    const state = deriveAgentWorkspaceState({ trace, liveEvents, pending: true })

    expect(state.phase).toBe("running")
    expect(state.activities.at(-1)?.label).toBe("Retrying explain_selection")
    expect(state.activities.at(-1)?.detail).toContain("Attempt 2/2")
  })

  it("distinguishes cancellation requested from cancellation completed", () => {
    const liveEvents = [event(0, "agent_start", { session_id: "session-1" })]

    const cancelling = deriveAgentWorkspaceState({
      trace,
      liveEvents,
      pending: true,
      cancelRequested: true,
    })
    expect(cancelling.phase).toBe("cancelling")

    const cancelled = deriveAgentWorkspaceState({
      trace,
      liveEvents: [
        ...liveEvents,
        event(1, "cancelled", { message: "Agent run cancelled before tool." }),
      ],
      pending: false,
      cancelledMessage: "Agent run cancelled before tool.",
    })
    expect(cancelled.phase).toBe("cancelled")
    expect(cancelled.errorMessage).toContain("cancelled")
  })
})
