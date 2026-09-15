// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { KnowledgeRetrievalControl } from "./KnowledgeRetrievalControl"

const fetchMock = vi.fn<typeof fetch>()

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
}

function renderControl({ documents = [document()] }: { documents?: ReturnType<typeof document>[] } = {}) {
  fetchMock.mockImplementation(async (input) => String(input).endsWith("/runtime")
    ? json({ enabled: true, embedding_provider: "qwen3", embedding_model: "Qwen3", embedding_status: "ready", device: "cuda", dimension: 1024, vector_store_provider: "qdrant", collection_name: "knowledge", document_count: documents.length, ready_document_count: documents.length, indexed_chunk_count: 12, max_file_bytes: 1 })
    : json({ total: documents.length, documents }))
  vi.stubGlobal("fetch", fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onEnabledChange = vi.fn()
  const onScopeChange = vi.fn()
  render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <KnowledgeRetrievalControl enabled={false} selectedDocumentIds={[]} disabled={false} onEnabledChange={onEnabledChange} onScopeChange={onScopeChange} />
      </QueryClientProvider>
    </MemoryRouter>,
  )
  return { onEnabledChange, onScopeChange }
}

function document() {
  return { document_id: "doc-1", title: "Paper.pdf", source_uri: "file:///paper.pdf", source_type: "pdf", status: "ready" as const, chunk_count: 12, indexed_at: null, error: "", content_hash: "hash", parser_version: "parser", chunker_version: "chunker", embedding_model: "qwen3", embedding_dimension: 1024 }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

describe("Knowledge retrieval control", () => {
  it("keeps retrieval separate from Chat context and reports availability", async () => {
    const { onEnabledChange } = renderControl()
    expect(await screen.findByText("1 documents available")).not.toBeNull()
    const toggle = screen.getByRole("switch", { name: "Search knowledge base" })
    await userEvent.click(toggle)
    expect(onEnabledChange).toHaveBeenCalledWith(true)
  })

  it("shows an actionable empty state when no indexed documents exist", async () => {
    renderControl({ documents: [] })
    expect(await screen.findByText("Knowledge base is empty")).not.toBeNull()
    expect(screen.getByRole("link", { name: "Open Knowledge Base" }).getAttribute("href")).toBe("/knowledge")
    expect((screen.getByRole("switch", { name: "Search knowledge base" }) as HTMLButtonElement).disabled).toBe(true)
  })
})
