import { afterEach, describe, expect, it, vi } from "vitest"

import {
  getAgentCatalog,
  getAgentRuntimeDebugRun,
  getAgentRuntimeDebugRuns,
} from "./agent-runtime-debug"

afterEach(() => vi.unstubAllGlobals())

describe("agent runtime debug api", () => {
  it("requests the public catalog and read-only run projections", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("[]", { status: 200 }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await getAgentCatalog()
    await getAgentRuntimeDebugRuns(24)
    await getAgentRuntimeDebugRun("run/debug 1")

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/agent/catalog")
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/agent/runtime/debug/runs?limit=24")
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain("/api/agent/runtime/debug/runs/run%2Fdebug%201")
  })
})
