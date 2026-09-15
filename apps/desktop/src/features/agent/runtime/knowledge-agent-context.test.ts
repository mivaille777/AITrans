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

  it("serializes canonical canvas relations without treating them as evidence", () => {
    const resolved = resolveKnowledgeAgentContext({
      item: evidence,
      writeback: null,
      canvas: {
        boardId: "board-1",
        boardName: "PID research",
        scopeLabel: "Selected cards",
      },
      relations: [
        {
          relationId: "relation-1",
          sourceItemId: "insight-1",
          sourceTitle: "LLM refinement insight",
          targetItemId: "evidence-1",
          targetTitle: "Safety-constrained Bayesian optimization",
          relationType: "supports",
          label: "User-confirmed support edge",
          origin: "manual",
          confidence: null,
        },
      ],
    })

    expect(resolved?.sourceText).toContain("Canvas relationship context")
    expect(resolved?.sourceText).toContain("[R1] LLM refinement insight")
    expect(resolved?.sourceText).toContain("--supports-->")
    expect(resolved?.sourceText).toContain("origin=manual")
    expect(resolved?.sourceText).toContain("not independent factual evidence")
    expect(resolved?.relations).toHaveLength(1)
    expect(resolved?.canvas?.boardName).toBe("PID research")
  })
})
