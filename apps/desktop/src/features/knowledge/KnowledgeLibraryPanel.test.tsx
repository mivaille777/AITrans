// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { desktop } from "../../desktop"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import type {
  KnowledgeDocument,
  KnowledgeDocumentStatus,
  KnowledgeItem,
  KnowledgeItemType,
} from "./knowledge-types"
import { useKnowledgeLibrary } from "./useKnowledgeLibrary"

const fetchMock = vi.fn<typeof fetch>()

function document(status: KnowledgeDocumentStatus, overrides: Partial<KnowledgeDocument> = {}): KnowledgeDocument {
  return {
    document_id: `doc-${status}`,
    title: `${status} paper.pdf`,
    source_uri: `file:///C:/papers/${status}.pdf`,
    source_type: "pdf",
    status,
    chunk_count: status === "ready" ? 12 : 0,
    indexed_at: status === "ready" ? "2026-08-24T00:00:00Z" : null,
    error: "",
    content_hash: "hash",
    parser_version: "basic@1",
    chunker_version: "structure@1",
    embedding_model: "qwen3",
    embedding_dimension: 1024,
    ...overrides,
  }
}

function item(
  itemType: KnowledgeItemType,
  overrides: Partial<KnowledgeItem> = {},
): KnowledgeItem {
  const id = overrides.item_id ?? `item-${itemType}`
  return {
    item_id: id,
    item_type: itemType,
    title: overrides.title ?? `${itemType} card`,
    summary: overrides.summary ?? "",
    resource_document_id: overrides.resource_document_id ?? null,
    source_uri: overrides.source_uri ?? "",
    metadata: overrides.metadata ?? {},
    created_at: overrides.created_at ?? "2026-09-07T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-09-07T00:00:00Z",
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function runtime(documentCount = 1) {
  return {
    enabled: true,
    embedding_provider: "qwen3",
    embedding_model: "Qwen3-Embedding-0.6B",
    embedding_status: "ready",
    device: "cuda",
    dimension: 1024,
    vector_store_provider: "qdrant",
    collection_name: "knowledge",
    document_count: documentCount,
    ready_document_count: documentCount,
    indexed_chunk_count: documentCount * 12,
    max_file_bytes: 1,
  }
}

function renderLibrary(initialEntries = ["/knowledge"]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <QueryClientProvider client={client}>
        <LibraryHarness />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

function LibraryHarness() {
  return <KnowledgeLibraryPanel library={useKnowledgeLibrary()} />
}

function installLibraryResponses({
  documents = [],
  items = [],
}: {
  documents?: KnowledgeDocument[]
  items?: KnowledgeItem[]
}) {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith("/api/knowledge/runtime")) return jsonResponse(runtime(documents.length))
    if (url.endsWith("/api/knowledge/items")) return jsonResponse({ total: items.length, items })
    if (url.endsWith("/api/knowledge/documents")) return jsonResponse({ total: documents.length, documents })
    return jsonResponse({ detail: "Unexpected test request" }, 500)
  })
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock)
  vi.spyOn(desktop.files, "pickKnowledgeDocument").mockResolvedValue("C:\\papers\\new.pdf")
  vi.spyOn(desktop.files, "openEvidenceSource").mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

describe("Knowledge Card Library", () => {
  it("renders resource-backed and semantic cards in one grid", async () => {
    const ready = document("ready", { title: "Safe BO paper" })
    installLibraryResponses({
      documents: [ready],
      items: [
        item("paper", {
          title: "Safe BO paper",
          resource_document_id: ready.document_id,
          source_uri: ready.source_uri,
        }),
        item("note", { title: "Reading note", summary: "Bounded LLM reasoning." }),
      ],
    })

    renderLibrary()

    expect(await screen.findByRole("heading", { name: "Knowledge Library" })).not.toBeNull()
    expect(screen.getByText("Safe BO paper")).not.toBeNull()
    expect(screen.getByText("Reading note")).not.toBeNull()
    expect(screen.getByText("Ready")).not.toBeNull()
    expect(screen.getByText("Bounded LLM reasoning.")).not.toBeNull()
  }, 10_000)

  it("creates a semantic note card through the workspace API", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/api/knowledge/runtime")) return jsonResponse(runtime(0))
      if (url.endsWith("/api/knowledge/documents")) return jsonResponse({ total: 0, documents: [] })
      if (url.endsWith("/api/knowledge/items") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({
          item_type: "note",
          title: "Mechanism note",
          summary: "Connect response evidence to control reasoning.",
        })
        return jsonResponse(item("note", { title: "Mechanism note" }), 201)
      }
      if (url.endsWith("/api/knowledge/items")) return jsonResponse({ total: 0, items: [] })
      return jsonResponse({ detail: "Unexpected test request" }, 500)
    })

    renderLibrary()
    await userEvent.click(await screen.findByRole("button", { name: "New card" }))
    const dialog = screen.getByRole("dialog", { name: "Create knowledge card" })
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Title" }), "Mechanism note")
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Summary" }),
      "Connect response evidence to control reasoning.",
    )
    await userEvent.click(within(dialog).getByRole("button", { name: "Create card" }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).endsWith("/api/knowledge/items") && init?.method === "POST")).toBe(true))
  })

  it("imports a selected document without changing the existing document API", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/api/knowledge/runtime")) return jsonResponse(runtime(0))
      if (url.endsWith("/api/knowledge/items")) return jsonResponse({ total: 0, items: [] })
      if (url.endsWith("/api/knowledge/documents") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ path: "C:\\papers\\new.pdf" })
        return jsonResponse({ document: document("ready"), reused_existing: false, elapsed_ms: 12 }, 201)
      }
      if (url.endsWith("/api/knowledge/documents")) return jsonResponse({ total: 0, documents: [] })
      return jsonResponse({ detail: "Unexpected test request" }, 500)
    })

    renderLibrary()
    await userEvent.click(await screen.findByRole("button", { name: "Add document" }))
    await userEvent.click(screen.getByRole("button", { name: "Browse files" }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).endsWith("/api/knowledge/documents") && init?.method === "POST")).toBe(true))
    expect(desktop.files.pickKnowledgeDocument).toHaveBeenCalledOnce()
  })

  it("filters the unified grid by card type", async () => {
    installLibraryResponses({
      items: [
        item("paper", { title: "Optimization paper" }),
        item("note", { title: "Optimization note" }),
      ],
    })

    renderLibrary()
    expect(await screen.findByText("Optimization paper")).not.toBeNull()
    const filterBar = screen.getByLabelText("Knowledge card type filter")
    await userEvent.click(within(filterBar).getByRole("button", { name: "note" }))

    expect(screen.getByText("Optimization note")).not.toBeNull()
    expect(screen.queryByText("Optimization paper")).toBeNull()
  })

  it("removes only the source index for a resource-backed card", async () => {
    const ready = document("ready")
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/api/knowledge/runtime")) return jsonResponse(runtime())
      if (url.endsWith("/api/knowledge/items")) {
        return jsonResponse({ total: 1, items: [item("paper", {
          title: ready.title,
          resource_document_id: ready.document_id,
          source_uri: ready.source_uri,
        })] })
      }
      if (url.endsWith(`/api/knowledge/documents/${ready.document_id}`) && init?.method === "DELETE") {
        return jsonResponse({ document_id: ready.document_id, deleted: true, source_file_preserved: true })
      }
      if (url.endsWith("/api/knowledge/documents")) return jsonResponse({ total: 1, documents: [ready] })
      return jsonResponse({ detail: "Unexpected test request" }, 500)
    })

    renderLibrary()
    await userEvent.click(await screen.findByLabelText(`More actions for ${ready.title}`))
    await userEvent.click(screen.getByRole("button", { name: "Remove source index" }))
    await userEvent.click(within(screen.getByRole("alertdialog", { name: "Remove from Knowledge Base" })).getByRole("button", { name: "Remove" }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).includes(`/api/knowledge/documents/${ready.document_id}`) && init?.method === "DELETE")).toBe(true))
    expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).includes("/api/knowledge/items/") && init?.method === "DELETE")).toBe(false)
  })

  it("reindexes a resource-backed card from its action menu", async () => {
    const ready = document("ready")
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/api/knowledge/runtime")) return jsonResponse(runtime())
      if (url.endsWith("/api/knowledge/items")) return jsonResponse({ total: 1, items: [item("paper", {
        title: ready.title,
        resource_document_id: ready.document_id,
        source_uri: ready.source_uri,
      })] })
      if (url.endsWith(`/api/knowledge/documents/${ready.document_id}/reindex`) && init?.method === "POST") {
        return jsonResponse({ document: document("indexing"), reused_existing: false, elapsed_ms: 3 })
      }
      if (url.endsWith("/api/knowledge/documents")) return jsonResponse({ total: 1, documents: [ready] })
      return jsonResponse({ detail: "Unexpected test request" }, 500)
    })

    renderLibrary()
    await userEvent.click(await screen.findByLabelText(`More actions for ${ready.title}`))
    await userEvent.click(screen.getByRole("button", { name: "Reindex source" }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/reindex"))).toBe(true))
  })

  it("opens the existing document detail drawer from a citation navigation target", async () => {
    const ready = document("ready")
    installLibraryResponses({
      documents: [ready],
      items: [item("paper", {
        title: ready.title,
        resource_document_id: ready.document_id,
        source_uri: ready.source_uri,
      })],
    })

    renderLibrary([`/knowledge?document=${ready.document_id}`])

    expect(await screen.findByRole("dialog", { name: `Document details ${ready.title}` })).not.toBeNull()
    expect(screen.getByText(/512 target tokens · 80 overlap/)).not.toBeNull()
  })
})
