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
    getRagDebugRun: vi.fn(),
    importRagDebugDataset: vi.fn(),
    listRagDebugCases: vi.fn().mockResolvedValue([evaluationCase]),
    listRagDebugChunks: vi.fn().mockResolvedValue({ chunks: [chunk], total: 1, page: 1, page_size: 50 }),
    listRagDebugConfigs: vi.fn().mockResolvedValue([config, { ...config, config_id: "candidate", name: "Candidate", active: false }]),
    listRagDebugDatasets: vi.fn().mockResolvedValue([dataset]),
    listRagDebugDocuments: vi.fn().mockResolvedValue([{ document_id: "doc-1", title: "unep_2023.pdf", source_uri: "", status: "ready", chunk_count: 1, updated_at: "" }]),
    saveRagDebugCase: vi.fn(),
    startRagDebugRun: vi.fn(),
    updateRagDebugCase: vi.fn(),
    updateRagDebugConfig: vi.fn(),
  }
})

import RagDebugStudioTrace from "./RagDebugStudioTrace"

afterEach(cleanup)

describe("RagDebugStudio", () => {
  it("renders all five interactive tabs", () => {
    render(<RagDebugStudioTrace />)

    expect(screen.getByText("RAG Debug Studio")).toBeTruthy()
    for (const label of ["Trace", "Chunks", "Evaluation", "Compare", "Datasets"]) {
      expect((screen.getByRole("button", { name: label }) as HTMLButtonElement).disabled).toBe(false)
    }
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

  it("shows evaluation metrics", () => {
    render(<RagDebugStudioTrace />)

    fireEvent.click(screen.getByRole("button", { name: "Evaluation" }))
    expect(screen.getByText("Recall@10")).toBeTruthy()
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
