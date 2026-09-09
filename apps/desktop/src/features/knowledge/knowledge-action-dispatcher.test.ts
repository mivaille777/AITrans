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
    ["summarize", "KNOWLEDGE_SUMMARIZE_REQUEST"],
    ["explain", "KNOWLEDGE_EXPLAIN_REQUEST"],
    ["translate", "KNOWLEDGE_TRANSLATE_REQUEST"],
    ["generate_notes", "KNOWLEDGE_NOTE_GENERATION_REQUEST"],
    ["ask_agent", "KNOWLEDGE_AGENT_QUERY_REQUEST"],
  ] as const)("maps %s to %s", (action, eventType) => {
    expect(dispatchKnowledgeAction(action, { item })).toEqual({
      type: eventType,
      item,
    })
  })
})
