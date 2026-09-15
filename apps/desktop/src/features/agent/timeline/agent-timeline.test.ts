import { describe, expect, it } from "vitest"

import type { AgentActivityItem } from "../state/agent-workspace-state"
import { deriveAgentTimelineStages, getAgentTimelineEventLabel } from "./agent-timeline"

function activity(
  sequence: number,
  eventType: AgentActivityItem["eventType"],
  tone: AgentActivityItem["tone"] = "neutral",
): AgentActivityItem {
  return {
    sequence,
    eventType,
    label: eventType,
    detail: `${eventType} detail`,
    tone,
  }
}

describe("Agent execution timeline", () => {
  it("projects a completed direct run into Decision, Action, Observation, and Result", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "agent_start"),
      activity(1, "context_ready", "success"),
      activity(2, "plan_ready"),
      activity(3, "tool_call"),
      activity(4, "tool_result", "success"),
      activity(5, "synthesis_ready", "success"),
      activity(6, "agent_end", "success"),
    ], false)

    expect(stages.map((stage) => stage.id)).toEqual([
      "decision",
      "tool",
      "observation",
      "result",
    ])
    expect(stages.map((stage) => stage.status)).toEqual([
      "complete",
      "complete",
      "complete",
      "complete",
    ])
  })

  it("projects an adaptive ReAct loop without inventing a separate hidden reasoning stage", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "agent_start"),
      activity(1, "context_ready", "success"),
      activity(2, "plan_ready"),
      activity(3, "react_started"),
      activity(4, "decision_ready"),
      activity(5, "tool_call"),
      activity(6, "tool_result", "success"),
      activity(7, "observation_ready", "success"),
      activity(8, "decision_ready"),
      activity(9, "synthesis_ready", "success"),
      activity(10, "agent_end", "success"),
    ], false)

    expect(stages.find((stage) => stage.id === "decision")?.activityCount).toBe(4)
    expect(stages.find((stage) => stage.id === "tool")?.activityCount).toBe(1)
    expect(stages.find((stage) => stage.id === "observation")?.activityCount).toBe(2)
    expect(stages.find((stage) => stage.id === "result")?.status).toBe("complete")
  })

  it("marks the latest runtime stage active while a run is still streaming", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "agent_start"),
      activity(1, "context_ready", "success"),
      activity(2, "react_started"),
      activity(3, "decision_ready"),
      activity(4, "tool_call"),
    ], true)

    expect(stages.find((stage) => stage.id === "decision")?.status).toBe("complete")
    expect(stages.find((stage) => stage.id === "tool")?.status).toBe("active")
    expect(stages.find((stage) => stage.id === "observation")?.status).toBe("idle")
  })

  it("moves the active stage back to Decision after an observation is consumed", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "react_started"),
      activity(1, "decision_ready"),
      activity(2, "tool_call"),
      activity(3, "tool_result", "success"),
      activity(4, "observation_ready", "success"),
      activity(5, "decision_ready"),
    ], true)

    expect(stages.find((stage) => stage.id === "decision")?.status).toBe("active")
    expect(stages.find((stage) => stage.id === "observation")?.status).toBe("complete")
  })

  it("keeps retries visible as a warning instead of hiding them behind later progress", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "decision_ready"),
      activity(1, "tool_call"),
      activity(2, "retry", "warning"),
      activity(3, "tool_result", "success"),
      activity(4, "observation_ready", "success"),
    ], true)

    expect(stages.find((stage) => stage.id === "tool")?.status).toBe("warning")
    expect(stages.find((stage) => stage.id === "observation")?.status).toBe("active")
  })

  it("shows Decision as active while setup is complete but no decision event has arrived", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "agent_start"),
      activity(1, "context_ready", "success"),
    ], true)

    expect(stages[0].status).toBe("active")
  })

  it("surfaces a ReAct execution limit as a result-stage warning", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "decision_ready"),
      activity(1, "tool_call"),
      activity(2, "observation_ready", "success"),
      activity(3, "react_limit_reached", "warning"),
    ], true)

    expect(stages.find((stage) => stage.id === "result")?.status).toBe("warning")
  })

  it("uses product-facing labels for setup and ReAct events", () => {
    expect(getAgentTimelineEventLabel("context_ready")).toBe("Setup")
    expect(getAgentTimelineEventLabel("decision_ready")).toBe("Decision")
    expect(getAgentTimelineEventLabel("tool_call")).toBe("Action")
    expect(getAgentTimelineEventLabel("observation_ready")).toBe("Observation")
    expect(getAgentTimelineEventLabel("react_limit_reached")).toBe("Result")
    expect(getAgentTimelineEventLabel("rag_evidence_selected")).toBe("Observation")
  })

  it("keeps RAG retrieval stages inside the existing observation timeline", () => {
    const stages = deriveAgentTimelineStages([
      activity(0, "tool_call"),
      activity(1, "rag_query_started"),
      activity(2, "rag_dense_completed", "success"),
      activity(3, "rag_sparse_completed", "success"),
      activity(4, "rag_fusion_completed", "success"),
      activity(5, "rag_rerank_completed", "success"),
      activity(6, "rag_evidence_selected", "success"),
      activity(7, "tool_result", "success"),
      activity(8, "observation_ready", "success"),
    ], false)

    expect(stages.find((stage) => stage.id === "observation")?.activityCount).toBe(8)
  })
})
