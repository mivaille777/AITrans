// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { AgentRunSnapshot, AgentTraceEvent } from "../../../api/agent"
import { TaskExecutionPanel } from "./TaskExecutionPanel"

const events: AgentTraceEvent[] = [
  { sequence: 1, event_type: "task_planned", timestamp: "now", run_id: "run-1", trace_id: "trace-1", elapsed_ms: 1, payload: { task_id: "document-1", role: "document", depends_on: [], output_kind: "document_analysis", status: "pending" } },
  { sequence: 2, event_type: "task_planned", timestamp: "now", run_id: "run-1", trace_id: "trace-1", elapsed_ms: 2, payload: { task_id: "research-1", role: "research", depends_on: ["document-1"], output_kind: "comparison", status: "pending" } },
  { sequence: 3, event_type: "task_started", timestamp: "now", run_id: "run-1", trace_id: "trace-1", elapsed_ms: 3, payload: { task_id: "document-1", status: "running", attempt: 1 } },
]

afterEach(cleanup)

describe("TaskExecutionPanel", () => {
  it("renders the dynamic plan and its dependencies", () => {
    render(<TaskExecutionPanel events={events} snapshot={null} running onRetry={() => undefined} />)
    expect(screen.getByText("document analysis deliverable")).not.toBeNull()
    expect(screen.getByText("依赖：document-1")).not.toBeNull()
    expect(document.querySelector('[data-task-id="document-1"]')?.getAttribute("data-task-status")).toBe("running")
  })

  it("uses the authoritative snapshot and exposes only retryable tasks", () => {
    const retry = vi.fn()
    const snapshot = {
      run_id: "run-1", trace_id: "trace-1", status: "failed", scope: {}, artifacts: [], events: [], resumable: false,
      retryable_task_ids: ["research-1"],
      plan: { tasks: [
        { task_id: "document-1", role: "document", objective: "Read A", depends_on: [], required: true, expected_output_kind: "document_analysis", plan_revision: 1 },
        { task_id: "research-1", role: "research", objective: "Compare", depends_on: ["document-1"], required: true, expected_output_kind: "comparison", plan_revision: 1 },
      ] },
      results: [
        { task_id: "document-1", attempt_id: "d:1", attempt_ordinal: 1, status: "succeeded", artifact_refs: [], evidence_refs: [], unmet_requirements: [], warnings: [], error_code: "" },
        { task_id: "research-1", attempt_id: "r:1", attempt_ordinal: 1, status: "failed", artifact_refs: [], evidence_refs: [], unmet_requirements: [], warnings: [], error_code: "provider_failed" },
      ],
    } satisfies AgentRunSnapshot
    render(<TaskExecutionPanel events={events} snapshot={snapshot} running={false} onRetry={retry} />)
    fireEvent.click(screen.getByRole("button", { name: "重试失败任务" }))
    expect(retry).toHaveBeenCalledWith("research-1")
    expect(document.querySelector('[data-task-id="document-1"]')?.getAttribute("data-task-status")).toBe("succeeded")
  })

  it("does not present a fast language call as expert collaboration", () => {
    const languageEvent = { ...events[0], event_type: "tool_call" as const, payload: { tool_name: "translate_selection" } }
    const { container } = render(<TaskExecutionPanel events={[languageEvent]} snapshot={null} running={false} onRetry={() => undefined} />)
    expect(container.textContent).toBe("")
  })
})
