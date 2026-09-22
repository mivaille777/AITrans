// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../../api/rag-debug", () => {
  const config = {
    config_id: "default",
    name: "Default",
    description: "",
    config: {
      enabled: true,
      advanced_parsing: {},
      visual_understanding: {},
      visual_retrieval: {},
      chunking: {},
      semantic_chunking: {},
      embedding: { model: "Qwen" },
      vector_store: {},
      retrieval: {
        dense_top_k: 30,
        sparse_top_k: 30,
        fusion_top_k: 20,
        final_top_k: 8,
        fusion: "rrf",
        small_to_big_enabled: true,
        small_to_big_top_k: 4,
        small_to_big_neighbor_radius: 1,
        small_to_big_max_tokens_per_anchor: 1200,
      },
      reranker: {},
    },
    active: true,
    requires_reindex: false,
    index_fingerprint: "",
    created_at: "",
    updated_at: "",
  }
  const evaluationCase = {
    case_id: "case-1",
    query: "What financing mechanisms support coastal resilience projects?",
    categories: [],
    relevant_chunk_ids: ["chunk-a"],
    relevance_grades: {},
    claims: [],
    no_answer: false,
    metadata: {},
    query_type: "Analytical",
    expected_answer: "",
    answerable: true,
    tags: [],
    notes: "",
    updated_at: "",
  }
  const chunk = {
    id: "chunk-a",
    document_id: "doc-1",
    title: "Nature-based solutions offer multiple co-benefits…",
    preview: "Nature-based solutions offer multiple co-benefits…",
    section: "2.1 Nature-based Solutions",
    section_path: ["2", "2.1"],
    page: 43,
    tokens: 318,
    overlap: 200,
    start: 2648,
    end: 5231,
    type: "Text",
    embedding: "Qwen",
    text: "Nature-based solutions offer multiple co-benefits…",
    metadata: {},
  }
  const dataset = { dataset_id: "dataset-1", name: "Evaluation set", description: "", case_count: 1, created_at: "", updated_at: "" }
  return {
    activateRagDebugConfig: vi.fn(),
    cancelRagDebugRun: vi.fn(),
    compareRagDebugDataset: vi.fn().mockResolvedValue({ dataset_id: dataset.dataset_id, baseline_config_id: "default", candidate_config_id: "default", cases: [{ case_id: evaluationCase.case_id, query: evaluationCase.query, baseline_rank: 1, candidate_rank: 1, baseline_latency_ms: 1, candidate_latency_ms: 1, baseline_chunk_ids: ["chunk-a"], candidate_chunk_ids: ["chunk-a"] }], metrics: {} }),
    createRagDebugConfig: vi.fn(),
    createRagDebugDataset: vi.fn(),
    deleteRagDebugCase: vi.fn(),
    deleteRagDebugDataset: vi.fn(),
    evaluateRagDebugDataset: vi.fn(),
    exportRagDebugDataset: vi.fn(),
    getRagDebugRun: vi.fn().mockResolvedValue({ run_id: "run-1", trace_id: "trace-1", status: "completed", query: "", config_id: "default", query_plan: {}, stages: [], candidates: [], context: { text: "", estimated_tokens: 0, included_evidence_ids: [], omitted_evidence_ids: [], source_count: 0 }, evidence: [], citations: [], answer: "", metadata: {}, error: "" }),
    importRagDebugDataset: vi.fn(),
    listRagDebugCases: vi.fn().mockResolvedValue([evaluationCase]),
    listRagDebugChunks: vi.fn().mockResolvedValue({ chunks: [chunk], total: 1, page: 1, page_size: 50 }),
    listRagDebugCompanionTraces: vi.fn().mockResolvedValue([
      { trace_id: "route-1", request_id: 1, conversation_id: "c1", query: "你是谁", knowledge_enabled: true, document_scope: "all", route: "system_identity", route_reason: "matched_system_identity", grounding_policy: "none", retrieval_skipped: true, verification_skipped: true, catalog_document_count: 0, retrieval: {}, verification: {}, fallback_applied: false, created_at: "" },
      { trace_id: "route-2", request_id: 2, conversation_id: "c1", query: "资料库有什么", knowledge_enabled: true, document_scope: "all", route: "knowledge_catalog", route_reason: "matched_knowledge_catalog", grounding_policy: "manifest", retrieval_skipped: true, verification_skipped: true, catalog_document_count: 3, retrieval: {}, verification: {}, fallback_applied: false, created_at: "" },
      { trace_id: "route-3", request_id: 3, conversation_id: "c1", query: "资料库里的 PID tuning 怎么做", knowledge_enabled: true, document_scope: "all", route: "knowledge_search", route_reason: "knowledge_capability_enabled", grounding_policy: "evidence", retrieval_skipped: false, verification_skipped: false, catalog_document_count: 0, retrieval: { evidence_count: 5 }, verification: { passed: true }, fallback_applied: false, created_at: "" },
    ]),
    listRagDebugConfigs: vi.fn().mockResolvedValue([config, { ...config, config_id: "candidate", name: "Candidate", active: false }]),
    listRagDebugDatasets: vi.fn().mockResolvedValue([dataset]),
    saveRagDebugCase: vi.fn(),
    startRagDebugRun: vi.fn().mockResolvedValue({ run_id: "run-1", trace_id: "trace-1", status: "completed" }),
    updateRagDebugCase: vi.fn(),
    updateRagDebugConfig: vi.fn(),
  }
})

vi.mock("../../api/knowledge", () => {
  const document = {
    document_id: "doc-1",
    title: "unep_2023.pdf",
    source_uri: "C:\\papers\\unep_2023.pdf",
    source_type: "pdf",
    status: "ready",
    chunk_count: 1,
    indexed_at: "2026-09-19T10:00:00Z",
    error: "",
    content_hash: "hash",
    parser_version: "pdf-v1",
    chunker_version: "semantic-v1",
    embedding_model: "Qwen",
    embedding_dimension: 384,
    structure_quality: "good",
    section_count: 2,
    reindex_recommended: false,
  }
  return {
    addKnowledgeDocument: vi.fn().mockResolvedValue({ document, reused_existing: false, elapsed_ms: 12 }),
    deleteKnowledgeDocument: vi.fn().mockResolvedValue({ document_id: document.document_id, deleted: true, source_file_preserved: true }),
    listKnowledgeDocuments: vi.fn().mockResolvedValue({ total: 1, documents: [document] }),
    reindexKnowledgeDocument: vi.fn().mockResolvedValue({ document, reused_existing: false, elapsed_ms: 8 }),
  }
})

vi.mock("../../desktop", () => ({
  desktop: {
    files: {
      pickKnowledgeDocument: vi.fn().mockResolvedValue("C:\\papers\\new.pdf"),
    },
  },
}))

import RagDebugStudioTrace from "./RagDebugStudioTrace"
import { addKnowledgeDocument, deleteKnowledgeDocument, reindexKnowledgeDocument } from "../../api/knowledge"
import { startRagDebugRun } from "../../api/rag-debug"
import { desktop } from "../../desktop"

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe("RagDebugStudio", () => {
  it("shows live Companion routes with distinct routing policies", async () => {
    render(<RagDebugStudioTrace />)

    await waitFor(() => expect(screen.getByText("system_identity")).toBeTruthy())
    expect(screen.getByText("knowledge_catalog")).toBeTruthy()
    expect(screen.getByText("knowledge_search")).toBeTruthy()
    expect(screen.getAllByText("Verification skipped").length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText("Verification passed")).toBeTruthy()
  })

  it("renders all six interactive tabs", () => {
    render(<RagDebugStudioTrace />)

    expect(screen.getByText("RAG Debug Studio")).toBeTruthy()
    for (const label of ["Trace", "Retrieval", "Chunks", "Evaluation", "Compare", "Datasets"]) {
      expect((screen.getByRole("button", { name: label }) as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it("opens the retrieval trace tab before a run", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Retrieval" }))
    expect(screen.getByText("No retrieval trace")).toBeTruthy()
  })

  it("switches to the chunk explorer and selects a chunk", async () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Chunks" }))
    expect(screen.getByText("Document Structure")).toBeTruthy()
    expect(screen.getByText("Chunks", { selector: "h2" })).toBeTruthy()
    await waitFor(() => expect(screen.getByRole("button", { name: /Nature-based solutions offer multiple co-benefits/ })).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: /Nature-based solutions offer multiple co-benefits/ }))
    expect(screen.getByText("2.1 Nature-based Solutions", { selector: "dd" })).toBeTruthy()
  })

  it("accepts a custom Top K value when starting a trace", async () => {
    render(<RagDebugStudioTrace />)

    fireEvent.change(screen.getByPlaceholderText(/Ask a question against/), {
      target: { value: "Find relevant evidence" },
    })
    fireEvent.change(screen.getByRole("spinbutton", { name: "Top K" }), {
      target: { value: "42" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Run trace" }))

    await waitFor(() =>
      expect(startRagDebugRun).toHaveBeenCalledWith({
        query: "Find relevant evidence",
        config_id: "default",
        top_k: 42,
        include_answer: false,
        knowledge_access_policy: "auto",
      }),
    )
  })

  it("imports and re-chunks a document through the Knowledge API", async () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Chunks" }))
    await waitFor(() => expect(screen.getByText("unep_2023.pdf")).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "Import document" }))
    await waitFor(() => expect(addKnowledgeDocument).toHaveBeenCalledWith("C:\\papers\\new.pdf"))

    vi.spyOn(window, "confirm").mockReturnValue(true)
    fireEvent.click(screen.getByRole("button", { name: "Re-chunk & reindex" }))
    await waitFor(() => expect(reindexKnowledgeDocument).toHaveBeenCalledWith("doc-1"))
  })

  it("removes indexed chunks while keeping the source file", async () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Chunks" }))
    await waitFor(() => expect(screen.getByRole("button", { name: /unep_2023\.pdf/ })).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: /unep_2023\.pdf/ }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy())

    vi.spyOn(window, "confirm").mockReturnValue(true)
    fireEvent.click(screen.getByRole("button", { name: "Remove" }))
    await waitFor(() => expect(deleteKnowledgeDocument).toHaveBeenCalledWith("doc-1"))
    expect(desktop.files.pickKnowledgeDocument).not.toHaveBeenCalled()
  })

  it("shows evaluation metrics", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Evaluation" }))
    expect(screen.getByText("Recall@10")).toBeTruthy()
    for (const label of [
      "Retrieval Trigger Precision",
      "Retrieval Trigger Recall",
      "Unnecessary Retrieval Rate",
      "Missing Retrieval Rate",
      "Scope Violation Rate",
      "Second-round Retrieval Rate",
      "Evidence Sufficiency Rate",
    ]) {
      expect(screen.getByText(label)).toBeTruthy()
    }
    expect(screen.getByText("Case Results")).toBeTruthy()
  })

  it("runs a comparison and renders returned query details", async () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Compare" }))
    await waitFor(() => expect((screen.getAllByRole("button", { name: "Compare" })[1] as HTMLButtonElement).disabled).toBe(false))
    expect(screen.getByText("Query Comparison")).toBeTruthy()
    fireEvent.click(screen.getAllByRole("button", { name: "Compare" })[1])
    await waitFor(() => expect(screen.getByText("What financing mechanisms support coastal resilience projects?")).toBeTruthy())
  })

  it("opens the dataset case editor", async () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Datasets" }))
    expect(screen.getByText("Evaluation Cases")).toBeTruthy()
    await waitFor(() => expect(screen.getByText("Case Details")).toBeTruthy())
    expect(screen.getByDisplayValue("What financing mechanisms support coastal resilience projects?")).toBeTruthy()
  })
})
