import { describe, expect, it } from "vitest"

import type { KnowledgeDocumentOutlineSection, KnowledgeDocumentSection } from "./knowledge-types"
import {
  buildPaperSelectionContext,
  buildSelectionCardTitle,
  paperPageLabel,
  resolveDerivedPaperRelationType,
  resolvePaperReaderSectionForPage,
  resolvePaperReaderSectionId,
} from "./paper-reader-state"

const section: KnowledgeDocumentSection = {
  document_id: "doc-1",
  section_id: "sec-method",
  heading: "Method",
  level: 2,
  section_path: ["Method"],
  page_start: 3,
  page_end: 5,
  text: "Before context. Safety-constrained Bayesian optimization keeps the candidate inside a bounded region. After context.",
  truncated: false,
}

function outlineSection(
  sectionId: string,
  pageStart = 1,
  pageEnd: number | null = pageStart,
  level = 1,
): KnowledgeDocumentOutlineSection {
  return {
    section_id: sectionId,
    heading: sectionId,
    level,
    parent_section_id: null,
    section_path: [sectionId],
    page_start: pageStart,
    page_end: pageEnd,
    block_count: 1,
    has_equations: false,
    has_tables: false,
    has_figures: false,
    reference_section: false,
    synthetic: false,
  }
}

describe("paper reader state", () => {
  it("resolves a preferred section only when it still exists", () => {
    const sections = [outlineSection("intro"), outlineSection("method")]
    expect(resolvePaperReaderSectionId(sections, "method")).toBe("method")
    expect(resolvePaperReaderSectionId(sections, "missing")).toBe("intro")
  })

  it("maps a PDF page to the most specific outline section", () => {
    const sections = [
      outlineSection("chapter", 3, 10, 1),
      outlineSection("method", 5, 7, 2),
      outlineSection("detail", 6, 6, 3),
    ]
    expect(resolvePaperReaderSectionForPage(sections, 6)?.section_id).toBe("detail")
    expect(resolvePaperReaderSectionForPage(sections, 8)?.section_id).toBe("chapter")
  })

  it("falls back to the nearest preceding section for an uncovered PDF page", () => {
    const sections = [outlineSection("intro", 1, 2), outlineSection("results", 5, 6)]
    expect(resolvePaperReaderSectionForPage(sections, 4)?.section_id).toBe("intro")
    expect(resolvePaperReaderSectionForPage(sections, 8)?.section_id).toBe("results")
  })

  it("captures bounded context around a selected passage", () => {
    const context = buildPaperSelectionContext(
      section,
      "Safety-constrained Bayesian optimization keeps the candidate inside a bounded region.",
      40,
    )
    expect(context.text).toContain("Safety-constrained")
    expect(context.contextBefore).toContain("Before context")
    expect(context.contextAfter).toContain("After context")
  })

  it("falls back cleanly when selected text is not in the section", () => {
    expect(buildPaperSelectionContext(section, "External quote")).toEqual({
      text: "External quote",
      contextBefore: "",
      contextAfter: "",
    })
  })

  it("keeps selection-derived cards distinct from the single paper reading note", () => {
    expect(resolveDerivedPaperRelationType("note")).toBe("derived_from")
    expect(resolveDerivedPaperRelationType("highlight")).toBe("derived_from")
    expect(resolveDerivedPaperRelationType("concept")).toBe("derived_from")
    expect(resolveDerivedPaperRelationType("evidence")).toBe("derived_from")
    expect(resolveDerivedPaperRelationType("note", "reading_note")).toBe("reading_note")
  })

  it("builds compact card titles and page labels", () => {
    expect(buildSelectionCardTitle("  a   short   finding  ", "Fallback")).toBe("a short finding")
    expect(buildSelectionCardTitle("x".repeat(100), "Fallback", 20)).toHaveLength(20)
    expect(paperPageLabel(3, 5)).toBe("Pages 3–5")
    expect(paperPageLabel(null, null)).toBe("Page —")
  })
})
