import { afterEach, expect, it, vi } from "vitest"
import { getTool, getTools } from "./tools"

afterEach(() => vi.unstubAllGlobals())

it("encodes filters and stable tool IDs", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => new Response(JSON.stringify({ items: [] }), { headers: { "Content-Type": "application/json" } }))
  vi.stubGlobal("fetch", fetchMock)
  await getTools({ q: "agent & paper", status: "enabled" })
  await getTool("builtin:search_knowledge_base")
  const url = new URL(String(fetchMock.mock.calls[0]?.[0]))
  expect(url.searchParams.get("q")).toBe("agent & paper")
  expect(url.searchParams.get("status")).toBe("enabled")
  expect(String(fetchMock.mock.calls[1]?.[0])).toContain("builtin%3Asearch_knowledge_base")
})
