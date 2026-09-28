// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { getAgentCatalog, getAgentRuntimeDebugRun, getAgentRuntimeDebugRuns } from "../../api/agent-runtime-debug"
import RuntimeDebugStudio from "./RuntimeDebugStudio"

vi.mock("../../api/agent-runtime-debug", () => ({
  getAgentCatalog: vi.fn(),
  getAgentRuntimeDebugRun: vi.fn(),
  getAgentRuntimeDebugRuns: vi.fn(),
}))

afterEach(cleanup)

describe("RuntimeDebugStudio", () => {
  it("shows safe run, task, tool, and shared language projections", async () => {
    vi.mocked(getAgentRuntimeDebugRuns).mockResolvedValue([{
      run_id: "run-1", trace_id: "trace-1", task_id: "task-root", status: "waiting",
      engine: "compat", graph_version: "ma10", state_schema_version: 2,
      created_at: "2026-09-28T00:00:00Z", updated_at: "2026-09-28T00:00:01Z",
      started_at: null, finished_at: null, duration_ms: null, event_count: 3,
      failure_reason: null, recovery_reason: null,
    }])
    vi.mocked(getAgentCatalog).mockResolvedValue({ agents: [{
      agent_id: "document", name: "Document Analyst", description: "Safe catalog entry",
      capabilities: ["reading"], version: "1", icon: "file-text",
    }] })
    vi.mocked(getAgentRuntimeDebugRun).mockResolvedValue({
      run_id: "run-1", trace_id: "trace-1", task_id: "task-root", status: "waiting",
      engine: "compat", graph_version: "ma10", state_schema_version: 2,
      created_at: "2026-09-28T00:00:00Z", updated_at: "2026-09-28T00:00:01Z",
      started_at: null, finished_at: null, duration_ms: null, event_count: 3,
      failure_reason: null, recovery_reason: null,
      route: null, plan: { plan_id: "plan-1", plan_revision: 1, task_count: 1 },
      tasks: [{ task_id: "task-doc", agent_id: "document", status: "partial", depends_on: [], required: true, output_kind: "document_analysis", attempts: [{ attempt: 1, status: "partial", duration_ms: 42, error_code: null }], artifact_refs: [{ artifact_id: "artifact-1", version: 1, kind: "document_analysis", content_hash: null }], duration_ms: 42, failure_reason: null }],
      tool_names: ["translate_selection"],
      related_ids: { rag_query_ids: null, sandbox_ids: null },
      events: [{ event_id: "event-1", sequence: 2, event_type: "task_partial", timestamp: "now", task_id: "task-doc", agent_id: "document", agent_version: "1", node_name: null, subgraph_path: null, status: "partial", attempt: 1, duration_ms: null, tool_name: null, reason_code: null, recovery_reason: null }],
    })

    render(<RuntimeDebugStudio />)

    expect(await screen.findByText("Document Analyst")).not.toBeNull()
    expect(screen.getByText("部分完成")).not.toBeNull()
    expect(screen.getByText(/共享语言 Capability/)).not.toBeNull()
    expect(screen.getByText("RAG query IDs：未记录")).not.toBeNull()
    expect(screen.getByText(/依赖：无 · 尝试：1 · 用时：42 ms/)).not.toBeNull()
    expect(screen.getByText(/artifact-1@1/)).not.toBeNull()
    await waitFor(() => expect(getAgentRuntimeDebugRun).toHaveBeenCalledWith("run-1"))
  })

  it("loads an associated run ID without fabricating absent fields", async () => {
    vi.mocked(getAgentRuntimeDebugRuns).mockResolvedValue([])
    vi.mocked(getAgentCatalog).mockResolvedValue({ agents: [] })
    vi.mocked(getAgentRuntimeDebugRun).mockRejectedValue(new Error("not found"))
    render(<RuntimeDebugStudio initialRunId="trusted-run" />)
    await waitFor(() => expect(getAgentRuntimeDebugRun).toHaveBeenCalledWith("trusted-run"))
    expect(screen.getByText("该 Run 暂无可用详情")).not.toBeNull()
  })
})
