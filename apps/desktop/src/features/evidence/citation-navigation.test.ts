import { describe, expect, it } from "vitest"

import { evidenceNavigation } from "./citation-model"
import type { AgentEvidenceItem } from "./evidence-types"

function evidence(overrides: Partial<AgentEvidenceItem> = {}): AgentEvidenceItem {
  return { evidence_id: "e-1", source_type: "knowledge", source_id: "doc/1", title: "Paper", resource_url: "file:///paper.pdf", location: "Page 12 · Section 3.4", excerpt: "Evidence", score: null, metadata: {}, ...overrides }
}

describe("citation navigation", () => {
  it("prefers structured provenance for page, section and Knowledge target", () => {
    expect(evidenceNavigation(evidence({ metadata: { page_number: 18, section_heading: "5.2" } }))).toEqual({ pageNumber: 18, sectionHeading: "5.2", knowledgeDocumentId: "doc/1" })
  })

  it("falls back to the verified display location without inventing a page", () => {
    expect(evidenceNavigation(evidence())).toEqual({ pageNumber: 12, sectionHeading: "3.4", knowledgeDocumentId: "doc/1" })
    expect(evidenceNavigation(evidence({ source_type: "web", source_id: "url", location: "" }))).toEqual({ pageNumber: null, sectionHeading: "", knowledgeDocumentId: "" })
  })
})
