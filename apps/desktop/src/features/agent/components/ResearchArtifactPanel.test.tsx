// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it } from "vitest"

import type { AgentRunSnapshot } from "../../../api/agent"
import { ResearchArtifactPanel } from "./ResearchArtifactPanel"

afterEach(cleanup)

describe("ResearchArtifactPanel", () => {
  it("renders comparison cells with conditions, evidence links, version, and verification", () => {
    const snapshot = {
      run_id: "run-1", trace_id: "trace-1", status: "completed", scope: {}, plan: {}, results: [], events: [], resumable: false, retryable_task_ids: [],
      artifacts: [{
        artifact_id: "comparison-1", version: 2, producer_task_id: "research-1", kind: "comparison", scope_ref: "scope-1", content: {}, evidence_refs: [],
        source_coverage: { complete: false, covered_refs: ["paper-a"], missing_refs: ["paper-b:table-2"], notes: [] },
        verification_status: "partial", verification_report: { issues: [] },
        cells: [{ dimension: "accuracy", source_label: "Paper A", value: "91%", conditions: "Dataset X", evidence_ids: ["ev-1"], unknown: false }],
      }],
    } satisfies AgentRunSnapshot
    const client = new QueryClient()
    render(<QueryClientProvider client={client}><ResearchArtifactPanel snapshot={snapshot} /></QueryClientProvider>)
    expect(screen.getByText("comparison · v2")).not.toBeNull()
    expect(screen.getByText("Dataset X")).not.toBeNull()
    expect(screen.getByRole("link", { name: /ev-1/ }).getAttribute("href")).toContain("evidence-ev-1")
    expect(screen.getByText(/paper-b:table-2/)).not.toBeNull()
  })
})
