import { afterEach, describe, expect, it, vi } from "vitest"

import {
  cancelAgentRuntimeRun,
  createAgentRuntimeRun,
  getAgentRuntimeRun,
} from "./agent-runtime"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("durable agent runtime api", () => {
  it("creates and controls canonical runs", async () => {
    const responses = [
      {
        task_id: "task-1",
        run_id: "run-1",
        trace_id: "trace-1",
        runtime_profile: "long_task",
        status: "queued",
        created_at: "2026-09-22T00:00:00Z",
        updated_at: "2026-09-22T00:00:00Z",
        started_at: null,
        finished_at: null,
        graph_version: "",
        state_schema_version: 0,
        checkpoint_id: "",
        budget_used_ms: 0,
      },
      {
        task_id: "task-1",
        run_id: "run-1",
        trace_id: "trace-1",
        runtime_profile: "long_task",
        status: "queued",
        created_at: "2026-09-22T00:00:00Z",
        updated_at: "2026-09-22T00:00:00Z",
        started_at: null,
        finished_at: null,
        graph_version: "",
        state_schema_version: 0,
        checkpoint_id: "",
        budget_used_ms: 0,
      },
      {
        task_id: "task-1",
        run_id: "run-1",
        trace_id: "trace-1",
        runtime_profile: "long_task",
        status: "cancelled",
        created_at: "2026-09-22T00:00:00Z",
        updated_at: "2026-09-22T00:00:01Z",
        started_at: null,
        finished_at: "2026-09-22T00:00:01Z",
        graph_version: "",
        state_schema_version: 0,
        checkpoint_id: "",
        budget_used_ms: 0,
      },
    ]
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(responses.shift()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const created = await createAgentRuntimeRun({
      session_id: "session-1",
      user_message: "Analyze",
      source_text: "",
      translated_text: "",
      source_language: "auto",
      target_language: "zh-CN",
      resource_url: "",
      resource_title: "",
      section_heading: "",
      context_before: "",
      context_after: "",
      source_kind: "desktop",
    })
    expect(created.run_id).toBe("run-1")
    await getAgentRuntimeRun(created.run_id)
    const cancelled = await cancelAgentRuntimeRun(created.run_id)
    expect(cancelled.status).toBe("cancelled")

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/agent/runs")
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/agent/runs/run-1")
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain("/api/agent/runs/run-1/cancel")
  })
})
