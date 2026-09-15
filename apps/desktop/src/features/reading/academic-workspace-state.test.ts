import { describe, expect, it } from "vitest"

import type {
  KnowledgeDocument,
  KnowledgeDocumentOutlineSection,
  KnowledgeDocumentSection,
} from "../knowledge/knowledge-types"
import {
  MAX_ACADEMIC_AGENT_CHARS,
  academicPageLabel,
  buildAcademicAgentText,
  resolveActiveAcademicDocumentId,
  resolveActiveAcademicSectionId,
} from "./academic-workspace-state"

function document(documentId: string, status: KnowledgeDocument["status"]): KnowledgeDocument {
  return {
    document_id: documentId,
    title: documentId,
    source_uri: `file:///${documentId}.pdf`,
    source_type: "pdf",
    status,
    chunk_count: 1,
    indexed_at: null,
    error: "",
    content_hash: "hash",
    parser_version: "parser",
    chunker_version: "chunker",
    embedding_model: "embedding",
    embedding_dimension: 1024,
  }
}

function section(sectionId: string, synthetic = false): KnowledgeDocumentOutlineSection {
  return {
    section_id: sectionId,
    heading: sectionId,
    level: 1,
    parent_section_id: null,
    section_path: [sectionId],
    page_start: 1,
    page_end: 2,
    block_count: 2,
    has_equations: false,
    has_tables: false,
    has_figures: false,
    reference_section: false,
    synthetic,
  }
}

describe("academic workspace state", () => {
  it("keeps an existing preferred document and otherwise prefers a ready document", () => {
    const documents = [document("indexing", "indexing"), document("ready", "ready")]

    expect(resolveActiveAcademicDocumentId(documents, "indexing")).toBe("indexing")
    expect(resolveActiveAcademicDocumentId(documents, "missing")).toBe("ready")
  })

  it("selects a real non-reference section before synthetic fallbacks", () => {
    const sections = [section("synthetic", true), section("method")]

    expect(resolveActiveAcademicSectionId(sections, "missing")).toBe("method")
    expect(resolveActiveAcademicSectionId(sections, "synthetic")).toBe("synthetic")
  })

  it("bounds long document sections before attaching them to the Agent", () => {
    const input: KnowledgeDocumentSection = {
      document_id: "doc",
      section_id: "method",
      heading: "Method",
      level: 1,
      section_path: ["Method"],
      page_start: 2,
      page_end: 4,
      text: "x".repeat(MAX_ACADEMIC_AGENT_CHARS + 200),
      truncated: false,
    }

    const bounded = buildAcademicAgentText(input)

    expect(bounded.text).toHaveLength(MAX_ACADEMIC_AGENT_CHARS)
    expect(bounded.truncated).toBe(true)
    expect(academicPageLabel(2, 4)).toBe("Pages 2–4")
  })
})
