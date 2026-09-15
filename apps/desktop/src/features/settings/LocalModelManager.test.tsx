// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LocalModelManager } from "./LocalModelManager"

const fetchMock = vi.fn<typeof fetch>()
const embedding = { model_id: "qwen3-embedding-0.6b", display_name: "Qwen3 Embedding 0.6B", repository_id: "Qwen/Embedding", state: "not_installed", installed: false, verified: false, source: "none", removable: false, path: "", disk_usage_bytes: 0, error: "" }
const reranker = { ...embedding, model_id: "qwen3-reranker-0.6b", display_name: "Qwen3 Reranker 0.6B", repository_id: "Qwen/Reranker" }

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
}

function renderManager() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><LocalModelManager /></QueryClientProvider>)
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

describe("Local model manager", () => {
  it("lists model roles and starts an explicit download", async () => {
    fetchMock.mockImplementation(async (_input, init) => init?.method === "POST"
      ? response({ model: { ...embedding, state: "installed", installed: true, verified: true }, changed: true })
      : response({ models_root: "C:/AITrans/models", models: [embedding, reranker] }))
    vi.stubGlobal("fetch", fetchMock)
    renderManager()

    expect(await screen.findByText("Qwen3 Embedding 0.6B")).not.toBeNull()
    expect(screen.getByText("Embedding · Qwen/Embedding")).not.toBeNull()
    await userEvent.click(screen.getAllByRole("button", { name: "Download" })[0]!)
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true))
  })

  it("requires a second click before removing installed weights", async () => {
    const installed = { ...embedding, state: "installed", installed: true, verified: true, source: "managed", removable: true, disk_usage_bytes: 1024 ** 3 }
    fetchMock.mockImplementation(async (_input, init) => init?.method === "DELETE"
      ? response({ model: embedding, changed: true })
      : response({ models_root: "C:/AITrans/models", models: [installed] }))
    vi.stubGlobal("fetch", fetchMock)
    renderManager()

    await userEvent.click(await screen.findByRole("button", { name: "Remove" }))
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false)
    await userEvent.click(screen.getByRole("button", { name: "Confirm remove" }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true))
  })

  it("uses a verified Hugging Face cache without offering removal", async () => {
    const cached = { ...embedding, state: "installed", installed: true, verified: true, source: "huggingface_cache", removable: false, disk_usage_bytes: 1024 ** 3 }
    fetchMock.mockResolvedValue(response({ models_root: "C:/AITrans/models", models: [cached] }))
    vi.stubGlobal("fetch", fetchMock)
    renderManager()

    expect(await screen.findByText("Files ready")).not.toBeNull()
    expect(screen.getByText("1.0 GB · Hugging Face cache")).not.toBeNull()
    expect(screen.getByRole("button", { name: "Verify" })).not.toBeNull()
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Download" })).toBeNull()
  })

  it("allows a managed download when the shared cache is incomplete", async () => {
    const invalidCache = { ...embedding, state: "invalid", source: "huggingface_cache", error: "missing required file: config.json" }
    fetchMock.mockResolvedValue(response({ models_root: "C:/AITrans/models", models: [invalidCache] }))
    vi.stubGlobal("fetch", fetchMock)
    renderManager()

    expect(await screen.findByText(/Hugging Face cache is incomplete/)).not.toBeNull()
    expect((screen.getByRole("button", { name: "Download" }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull()
  })
})
