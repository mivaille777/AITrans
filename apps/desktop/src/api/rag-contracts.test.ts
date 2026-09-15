import { afterEach, describe, expect, it, vi } from "vitest"

import {
  getKnowledgeDocument,
  getKnowledgeDocumentStatus,
  getKnowledgeRuntime,
} from "./knowledge"
import { downloadRagModel, listRagModels, removeRagModel, verifyRagModel } from "./rag-models"

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

describe("RAG frontend contracts", () => {
  it("addresses Knowledge detail, status and runtime endpoints", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input)
      if (path.endsWith("/status")) {
        return jsonResponse({ document_id: "doc/one", status: "ready", chunk_count: 8, indexed_at: null, error: "" })
      }
      if (path.endsWith("/runtime")) {
        return jsonResponse({ enabled: true, embedding_provider: "qwen3", embedding_model: "model", embedding_status: "ready", device: "cpu", dimension: 1024, vector_store_provider: "qdrant", collection_name: "knowledge", document_count: 1, ready_document_count: 1, indexed_chunk_count: 8, max_file_bytes: 1 })
      }
      return jsonResponse({ document_id: "doc/one", title: "Paper", source_uri: "file:///paper.pdf", source_type: "pdf", status: "ready", chunk_count: 8, indexed_at: null, error: "", content_hash: "hash", parser_version: "parser", chunker_version: "chunker", embedding_model: "model", embedding_dimension: 1024 })
    })
    vi.stubGlobal("fetch", fetchMock)

    await getKnowledgeDocument("doc/one")
    await getKnowledgeDocumentStatus("doc/one")
    const runtime = await getKnowledgeRuntime()

    expect(runtime.indexed_chunk_count).toBe(8)
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(expect.arrayContaining([
      expect.stringContaining("/documents/doc%2Fone"),
      expect.stringContaining("/documents/doc%2Fone/status"),
      expect.stringContaining("/api/knowledge/runtime"),
    ]))
  })

  it("addresses list, download, verify and remove model operations", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input)
      const model = { model_id: "qwen3-embedding-0.6b", display_name: "Qwen3 Embedding", repository_id: "Qwen/model", state: "installed", installed: true, verified: true, source: "huggingface_cache", removable: false, path: "C:/models/qwen", disk_usage_bytes: 1024, error: "" }
      return jsonResponse(path.endsWith("/models") ? { models_root: "C:/models", models: [model] } : path.endsWith("/verify") ? model : { model, changed: true })
    })
    vi.stubGlobal("fetch", fetchMock)

    const listed = await listRagModels()
    await downloadRagModel("qwen3-embedding-0.6b")
    await verifyRagModel("qwen3-embedding-0.6b")
    await removeRagModel("qwen3-embedding-0.6b")

    expect(listed.models).toHaveLength(1)
    expect(listed.models[0]?.source).toBe("huggingface_cache")
    expect(fetchMock.mock.calls.map(([, init]) => init?.method ?? "GET")).toEqual([
      "GET", "POST", "POST", "DELETE",
    ])
  })
})
