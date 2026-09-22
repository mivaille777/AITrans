import type { AgentTraceEvent } from "../../../api/agent"
import { describe, expect, it } from "vitest"
import { deriveAgentKnowledgeState } from "./agent-knowledge-state"

function event(
  eventType: AgentTraceEvent["event_type"],
  payload: Record<string, unknown>,
): AgentTraceEvent {
  return {
    sequence: 1,
    event_type: eventType,
    timestamp: "2026-09-22T00:00:00Z",
    run_id: "run-1",
    trace_id: "trace-1",
    elapsed_ms: 1,
    payload,
  }
}

describe("Agent knowledge state", () => {
  it("defaults the Agent policy to Auto and shows the current document scope", () => {
    const state = deriveAgentKnowledgeState({
      events: [],
      pending: false,
      contextTitle: "Paper",
      contextSection: "Measurement",
      documentCount: 1,
      contextMode: "reading",
    })

    expect(state.policyLabel).toBe("Auto")
    expect(state.scopeDisplay).toBe("Current document · Measurement")
    expect(state.statusDetail).toBe("Awaiting run")
  })

  it("shows evaluation while the Agent run is active", () => {
    const state = deriveAgentKnowledgeState({
      events: [],
      pending: true,
      contextSection: "Measurement",
      contextMode: "reading",
    })

    expect(state.status).toBe("evaluating")
    expect(state.statusDetail).toBe("Evaluating…")
  })

  it("projects a skipped decision as context sufficient", () => {
    const state = deriveAgentKnowledgeState({
      events: [
        event("knowledge_decision", {
          mode: "auto",
          should_retrieve: false,
          reason_code: "current_context_sufficient",
          scope_strategy: "attached_document",
        }),
        event("knowledge_scope_resolved", {
          strategy: "attached_document",
          document_count: 1,
          research_source_count: 0,
          workspace_selected: false,
        }),
        event("knowledge_skipped", {
          reason_code: "current_context_sufficient",
          scope_strategy: "attached_document",
        }),
      ],
      pending: false,
      contextSection: "Measurement",
      contextMode: "reading",
    })

    expect(state.statusDetail).toBe("Skipped · Context sufficient")
  })

  it("projects a retrieval decision with its resolved scope", () => {
    const state = deriveAgentKnowledgeState({
      events: [
        event("knowledge_decision", {
          mode: "auto",
          should_retrieve: true,
          reason_code: "document_grounding_required",
          scope_strategy: "attached_document",
        }),
        event("knowledge_scope_resolved", {
          strategy: "attached_document",
          document_count: 1,
          research_source_count: 0,
          workspace_selected: false,
        }),
      ],
      pending: false,
      contextSection: "Measurement",
      contextMode: "reading",
    })

    expect(state.statusDetail).toBe("Current document · Retrieval required")
  })
})
