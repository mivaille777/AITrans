import { describe, expect, it } from "vitest"

import type { KnowledgeItem } from "../../knowledge/knowledge-types"
import { resolveKnowledgeAgentContext } from "./knowledge-agent-context"

const evidence: KnowledgeItem = {
  item_id: "evidence-1",
  item_type: "evidence",
  title: "Safety-constrained Bayesian optimization",
  summary: "Selected evidence.",
  resource_document_id: null,
  source_uri: "file:///paper.pdf",
  metadata: {
    document_id: "doc-1",
    section_heading: "Methods",
    selection_text: "Selected evidence.",
    context_before: "Before evidence.",
    context_after: "After evidence.",
  },
  created_at: "2026-09-13T00:00:00Z",
  updated_at: "2026-09-13T00:00:00Z",
}

describe("knowledge agent context", () => {
  it("restores reader grounding from an evidence card", () => {
    const resolved = resolveKnowledgeAgentContext({
      item: evidence,
      writeback: {
        itemType: "insight",
        operation: "research",
        relationType: "derived_from",
      },
    })

    expect(resolved?.sourceText).toBe("Selected evidence.")
    expect(resolved?.documentIds).toEqual(["doc-1"])
    expect(resolved?.context.section_heading).toBe("Methods")
    expect(resolved?.context.context_before).toBe("Before evidence.")
    expect(resolved?.context.context_after).toBe("After evidence.")
    expect(resolved?.context.source_kind).toBe("knowledge_evidence")
    expect(resolved?.context.resource_url).toContain("knowledge-item://evidence-1")
    expect(resolved?.context.resource_url).toContain("type=insight")
  })
})
