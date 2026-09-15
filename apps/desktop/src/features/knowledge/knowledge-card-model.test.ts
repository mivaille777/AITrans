import { describe, expect, it } from "vitest"

import {
  knowledgeCardConfidence,
  knowledgeCardLabel,
  knowledgeCardProvenance,
  knowledgeCardSources,
  newKnowledgeCardMetadata,
} from "./knowledge-card-model"

describe("knowledge card model", () => {
  it("uses the canonical labels for semantic card types", () => {
    expect(knowledgeCardLabel("evidence")).toBe("Evidence")
    expect(knowledgeCardLabel("insight")).toBe("Insight")
    expect(knowledgeCardLabel("question")).toBe("Question")
  })

  it("clamps confidence into the user-visible range", () => {
    expect(knowledgeCardConfidence({ metadata: { confidence: 1.4 } })).toBe(1)
    expect(knowledgeCardConfidence({ metadata: { confidence: -0.3 } })).toBe(0)
    expect(knowledgeCardConfidence({ metadata: {} })).toBeNull()
  })

  it("keeps only valid evidence source descriptors", () => {
    expect(knowledgeCardSources({
      metadata: {
        sources: [
          { document_id: "doc-1", chunk_id: "chunk-2", page: 4 },
          { document_id: "" },
        ],
      },
    })).toEqual([{ document_id: "doc-1", chunk_id: "chunk-2", page: 4 }])
  })

  it("records explicit creation provenance", () => {
    const metadata = newKnowledgeCardMetadata("user")
    expect(knowledgeCardProvenance({ metadata })).toEqual({ created_by: "user" })
  })
})
