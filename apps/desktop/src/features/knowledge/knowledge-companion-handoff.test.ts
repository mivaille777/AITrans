import { describe, expect, it } from "vitest"

import type { KnowledgeItem } from "./knowledge-types"
import { buildKnowledgeCompanionHandoff, knowledgeCardDocumentIds } from "./knowledge-companion-handoff"

const evidence: KnowledgeItem = {
  item_id: "evidence-1",
  item_type: "evidence",
  title: "Bounded optimization evidence",
  summary: "Evidence summary.",
  resource_document_id: null,
  source_uri: "file:///paper.pdf",
  metadata: {
    document_id: "doc-1",
    selection_text: "Selected evidence.",
    section_heading: "Methods",
    context_before: "Before evidence.",
    context_after: "After evidence.",
    sources: [
      { document_id: "doc-1" },
      { document_id: "doc-2" },
    ],
  },
  created_at: "2026-09-13T00:00:00Z",
  updated_at: "2026-09-13T00:00:00Z",
}

const insight: KnowledgeItem = {
  ...evidence,
  item_id: "insight-1",
  item_type: "insight",
  title: "Research insight",
  summary: "The evidence supports bounded local refinement.",
  resource_document_id: "doc-1",
  metadata: {
    ...evidence.metadata,
    selection_text: undefined,
  },
}

describe("knowledge companion handoff", () => {
  it("uses selection evidence and enables retrieval over all grounded documents", () => {
    const handoff = buildKnowledgeCompanionHandoff(evidence, {
      targetLanguage: "zh-CN",
    })

    expect(handoff.source_text).toBe("Selected evidence.")
    expect(handoff.source_kind).toBe("knowledge_evidence")
    expect(handoff.section_heading).toBe("Methods")
    expect(handoff.context_before).toBe("Before evidence.")
    expect(handoff.context_after).toBe("After evidence.")
    expect(handoff.knowledge_enabled).toBe(true)
    expect(handoff.knowledge_document_ids).toEqual(["doc-1", "doc-2"])
    expect(handoff.resource_url).toBe("knowledge-item://evidence-1")
  })

  it("uses generated insight content instead of replaying the source quote", () => {
    const handoff = buildKnowledgeCompanionHandoff(insight)

    expect(handoff.source_text).toBe("The evidence supports bounded local refinement.")
    expect(handoff.ai_content).toBe("The evidence supports bounded local refinement.")
    expect(handoff.source_kind).toBe("knowledge_insight")
    expect(knowledgeCardDocumentIds(insight)).toEqual(["doc-1", "doc-2"])
  })
})
