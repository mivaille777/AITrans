import { describe, expect, it } from "vitest"

import type { AgentActivityItem } from "../state/agent-workspace-state"
import { deriveAgentDecision } from "./agent-decision"

function retryActivity(): AgentActivityItem {
  return {
    sequence: 3,
    eventType: "retry",
    label: "Retrying explain_selection",
    detail: "Attempt 2/2. temporary provider failure",
    tone: "warning",
  }
}

describe("Stage 9.4 Agent decision projection", () => {
  it("prioritizes explicit write confirmation", () => {
    const decision = deriveAgentDecision({
      phase: "confirmation_required",
      confirmationTool: "save_research_note",
      errorMessage: "",
      fallbackReason: "",
      activities: [],
    })

    expect(decision).toMatchObject({
      kind: "confirmation",
      toolName: "save_research_note",
      requiresConfirmation: true,
    })
  })

  it("keeps fallback reason and the triggering runtime error visible", () => {
    const decision = deriveAgentDecision({
      phase: "error",
      confirmationTool: "",
      errorMessage: "Agent planner returned an invalid structured plan.",
      fallbackReason: "no_safe_fallback",
      activities: [],
    })

    expect(decision?.kind).toBe("fallback")
    expect(decision?.detail).toContain("invalid structured plan")
    expect(decision?.detail).toContain("no_safe_fallback")
  })

  it("shows a terminal failure when no fallback is available", () => {
    const decision = deriveAgentDecision({
      phase: "error",
      confirmationTool: "",
      errorMessage: "Tool contract validation failed.",
      fallbackReason: "",
      activities: [],
    })

    expect(decision).toMatchObject({
      kind: "failure",
      tone: "danger",
    })
  })

  it("shows retry only while retry is the latest active runtime event", () => {
    const retrying = deriveAgentDecision({
      phase: "running",
      confirmationTool: "",
      errorMessage: "",
      fallbackReason: "",
      activities: [retryActivity()],
    })
    expect(retrying?.kind).toBe("retry")

    const progressed = deriveAgentDecision({
      phase: "running",
      confirmationTool: "",
      errorMessage: "",
      fallbackReason: "",
      activities: [
        retryActivity(),
        {
          sequence: 4,
          eventType: "tool_result",
          label: "Tool completed",
          detail: "Observation returned.",
          tone: "success",
        },
      ],
    })
    expect(progressed).toBeNull()
  })

  it("distinguishes cancellation request from completed cancellation", () => {
    const cancelling = deriveAgentDecision({
      phase: "cancelling",
      confirmationTool: "",
      errorMessage: "",
      fallbackReason: "",
      activities: [],
    })
    expect(cancelling?.kind).toBe("cancelling")

    const cancelled = deriveAgentDecision({
      phase: "cancelled",
      confirmationTool: "",
      errorMessage: "Agent run cancelled before tool execution.",
      fallbackReason: "",
      activities: [],
    })
    expect(cancelled?.kind).toBe("cancelled")
  })

  it("stays hidden for ordinary completed runs", () => {
    const decision = deriveAgentDecision({
      phase: "completed",
      confirmationTool: "",
      errorMessage: "",
      fallbackReason: "",
      activities: [],
    })

    expect(decision).toBeNull()
  })
})
