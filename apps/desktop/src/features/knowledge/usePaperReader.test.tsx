// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  createKnowledgeItem,
  createKnowledgeRelation,
  getKnowledgeDocumentOutline,
  getKnowledgeDocumentPreviewUrl,
  getKnowledgeDocumentSection,
  listKnowledgeRelations,
} from "./knowledge-api"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"
import { usePaperReader } from "./usePaperReader"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"

vi.mock("./knowledge-api", () => ({
  createKnowledgeItem: vi.fn(),
  createKnowledgeRelation: vi.fn(),
  deleteKnowledgeItem: vi.fn(),
  getKnowledgeDocumentOutline: vi.fn(),
  getKnowledgeDocumentPreviewUrl: vi.fn(() => "http://127.0.0.1:8000/preview.pdf"),
  getKnowledgeDocumentSection: vi.fn(),
  listKnowledgeRelations: vi.fn(),
  updateKnowledgeItem: vi.fn(),
}))

vi.mock("../../api/translation", () => ({ translateText: vi.fn() }))

const paper = {
  item_id: "paper-1",
  item_type: "paper" as const,
  title: "Safety-constrained control",
  summary: "Paper summary",
  resource_document_id: "doc-1",
  source_uri: "file:///papers/control.pdf",
  metadata: {},
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
}

const indexedDocument = {
  document_id: "doc-1",
  title: paper.title,
  source_uri: paper.source_uri,
  source_type: "pdf",
  status: "ready" as const,
  chunk_count: 12,
  indexed_at: "2026-09-15T00:00:00Z",
  error: "",
  content_hash: "hash",
  parser_version: "1",
  chunker_version: "1",
  embedding_model: "local",
  embedding_dimension: 384,
}

const section = {
  document_id: "doc-1",
  section_id: "method",
  heading: "Method",
  level: 2,
  section_path: ["Method"],
  page_start: 6,
  page_end: 8,
  text: "Before context. Selected safety argument. After context.",
  truncated: false,
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function testControllers() {
  const library = {
    itemsQuery: { data: { items: [paper] } },
    documentsQuery: { data: { documents: [indexedDocument] } },
  } as unknown as KnowledgeLibraryController
  const useAcademicReadingContext = vi.fn()
  const workspace = {
    sourceLanguage: "auto",
    targetLanguage: "zh-CN",
    useAcademicReadingContext,
  } as unknown as TranslationWorkspaceController
  return { library, workspace, useAcademicReadingContext }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getKnowledgeDocumentPreviewUrl).mockReturnValue("http://127.0.0.1:8000/preview.pdf")
  vi.mocked(getKnowledgeDocumentOutline).mockResolvedValue({
    document_id: "doc-1",
    title: paper.title,
    page_count: 10,
    section_count: 1,
    sections: [{
      section_id: "method",
      heading: "Method",
      level: 2,
      parent_section_id: null,
      section_path: ["Method"],
      page_start: 6,
      page_end: 8,
      block_count: 3,
      has_equations: false,
      has_tables: false,
      has_figures: false,
      reference_section: false,
      synthetic: false,
    }],
  })
  vi.mocked(getKnowledgeDocumentSection).mockResolvedValue(section)
  vi.mocked(listKnowledgeRelations).mockResolvedValue({ total: 0, relations: [] })
  vi.mocked(createKnowledgeRelation).mockResolvedValue({
    relation_id: "relation-1",
    source_item_id: "evidence-1",
    target_item_id: "paper-1",
    relation_type: "derived_from",
    origin: "manual",
    label: "",
    confidence: null,
    metadata: {},
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
  })
  vi.mocked(createKnowledgeItem).mockImplementation(async (payload) => ({
    item_id: "evidence-1",
    item_type: payload.item_type,
    title: payload.title,
    summary: payload.summary ?? "",
    resource_document_id: null,
    source_uri: payload.source_uri ?? "",
    metadata: payload.metadata ?? {},
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
  }))
})

describe("usePaperReader PDF grounding", () => {
  it("stores Evidence with selected text, section context, and PDF page provenance", async () => {
    const { library, workspace } = testControllers()
    const { result } = renderHook(() => usePaperReader("paper-1", library, workspace), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current.sectionQuery.isSuccess).toBe(true))

    await act(async () => {
      await result.current.createDerivedMutation.mutateAsync({
        itemType: "evidence",
        source: "pdf",
        text: "Selected safety argument.",
        pageNumber: 7,
      })
    })

    expect(createKnowledgeItem).toHaveBeenCalledWith(expect.objectContaining({
      item_type: "evidence",
      metadata: expect.objectContaining({
        selection_text: "Selected safety argument.",
        selection_source: "pdf",
        pdf_page_number: 7,
        section_heading: "Method",
        provenance: "paper_reader_pdf_selection",
        evidence_kind: "paper_pdf_selection",
        sources: [expect.objectContaining({ page: 7, section: "Method" })],
      }),
    }))
  })

  it("attaches selection text, nearby section context, and PDF page to Ask AI", async () => {
    const { library, workspace, useAcademicReadingContext } = testControllers()
    const { result } = renderHook(() => usePaperReader("paper-1", library, workspace), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current.sectionQuery.isSuccess).toBe(true))

    let attached = false
    await act(async () => {
      attached = await result.current.attachSelectionToAgent({
        source: "pdf",
        text: "Selected safety argument.",
        pageNumber: 7,
      })
    })

    expect(attached).toBe(true)
    expect(useAcademicReadingContext).toHaveBeenCalledWith(expect.objectContaining({
      context_id: "knowledge:doc-1:method:pdf:7:selection",
      text: "Selected safety argument.",
      section_heading: "Method · PDF page 7",
      context_before: expect.stringContaining("Before context"),
      context_after: expect.stringContaining("After context"),
    }))
  })
})
