// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, it } from "vitest"

import KnowledgeCardRenderer from "./KnowledgeCardRenderer"
import type { KnowledgeItem } from "./knowledge-types"

const now = "2026-09-15T00:00:00Z"

function card(metadata: KnowledgeItem["metadata"]): KnowledgeItem {
  return {
    item_id: "evidence-1",
    item_type: "evidence",
    title: "Selected evidence",
    summary: "A selected passage from the paper.",
    resource_document_id: null,
    source_uri: "file:///paper.pdf",
    metadata,
    created_at: now,
    updated_at: now,
  }
}

afterEach(cleanup)

describe("KnowledgeCardRenderer reader provenance", () => {
  it("shows PDF page and section provenance", () => {
    render(<KnowledgeCardRenderer item={card({
      selection_source: "pdf",
      pdf_page_number: 7,
      section_heading: "3.2 Safety Gate",
    })} />)

    screen.getByText(/PDF p\.7 · 3\.2 Safety Gate/)
  })

  it("shows text section provenance without pretending it has a PDF page", () => {
    render(<KnowledgeCardRenderer item={card({
      selection_source: "text",
      section_heading: "Introduction",
    })} />)

    screen.getByText(/Text · Introduction/)
  })
})
