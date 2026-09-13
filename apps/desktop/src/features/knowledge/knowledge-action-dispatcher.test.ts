import { describe, expect, it } from "vitest"

import { dispatchKnowledgeAction } from "./knowledge-action-dispatcher"
import type { KnowledgeItem } from "./knowledge-types"

const item: KnowledgeItem = {
  item_id: "paper-1",
  item_type: "paper",
  title: "Agent Planning",
  summary: "A paper about planning agents.",
  resource_document_id: "doc-1",
  source_uri: "file:///papers/agent-planning.pdf",
  metadata: {},
  created_at: "2026-09-09T00:00:00Z",
  updated_at: "2026-09-09T00:00:00Z",
}

describe("knowledge action dispatcher", () => {
  it.each([
    ["summarize", "KNOWLEDGE_SUMMARIZE_REQUEST", "insight", "summarize", true],
    ["explain", "KNOWLEDGE_EXPLAIN_REQUEST", "insight", "explain", true],
    ["translate", "KNOWLEDGE_TRANSLATE_REQUEST", "note", "translate", true],
    ["generate_notes", "KNOWLEDGE_NOTE_GENERATION_REQUEST", "note", "generate_notes", true],
    ["ask_agent", "KNOWLEDGE_AGENT_QUERY_REQUEST", "insight", "question", false],
  ] as const)(
    "maps %s to %s with canonical writeback intent",
    (action, eventType, itemType, operation, autoSubmit) => {
      const event = dispatchKnowledgeAction(action, { item })

      expect(event?.type).toBe(eventType)
      expect(event?.item).toEqual(item)
      expect(event?.agentRequest.autoSubmit).toBe(autoSubmit)
      expect(event?.agentRequest.writeback).toEqual({
        itemType,
        operation,
        relationType: "derived_from",
      })
    },
  )

  it("keeps Ask Agent interactive instead of auto-submitting a placeholder question", () => {
    const event = dispatchKnowledgeAction("ask_agent", { item })

    expect(event?.agentRequest.prompt).toBe("")
    expect(event?.agentRequest.autoSubmit).toBe(false)
  })
})
