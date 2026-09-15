// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import type { AgentActivityItem } from "../state/agent-workspace-state"
import { AgentRetrievalActivity } from "./AgentRetrievalActivity"

function activity(sequence: number, eventType: AgentActivityItem["eventType"], detail: string): AgentActivityItem {
  return { sequence, eventType, detail, label: eventType, tone: "success" }
}

afterEach(cleanup)

describe("Agent retrieval activity", () => {
  it("shows the local retrieval pipeline and keeps durations secondary", () => {
    render(<AgentRetrievalActivity running={false} activities={[
      activity(1, "rag_query_started", "hybrid"),
      activity(2, "rag_query_rewritten", "2 bounded queries"),
      activity(3, "rag_dense_completed", "12 candidates · 81 ms"),
      activity(4, "rag_sparse_completed", "9 candidates · 12 ms"),
      activity(5, "rag_fusion_completed", "10 fused candidates · 2 ms"),
      activity(6, "rag_rerank_completed", "8 final candidates · 182 ms"),
      activity(7, "rag_evidence_selected", "8 verified sources · 281 ms"),
    ]} />)

    expect(screen.getByRole("region", { name: "Knowledge retrieval activity" })).not.toBeNull()
    expect(screen.getByText("Query rewrite")).not.toBeNull()
    expect(screen.getByText("Dense retrieval")).not.toBeNull()
    expect(screen.getByText("Reranking")).not.toBeNull()
    expect(screen.getByText("Evidence selected")).not.toBeNull()
    expect(screen.getByText("182 ms")).not.toBeNull()
  })

  it("shows an explicit fallback instead of implying evidence was selected", () => {
    render(<AgentRetrievalActivity running={false} activities={[
      activity(1, "rag_query_started", "hybrid"),
      { ...activity(2, "rag_fallback", "No verified evidence was selected."), tone: "warning" },
    ]} />)
    expect(screen.getByText("Retrieval fallback")).not.toBeNull()
    expect(screen.queryByText("Evidence selected")).toBeNull()
  })
})
