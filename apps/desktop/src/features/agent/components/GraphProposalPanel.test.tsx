// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { AgentArtifact } from "../../../api/agent"
import { GraphProposalPanel } from "./GraphProposalPanel"

const api = vi.hoisted(() => ({ commit: vi.fn(), accept: vi.fn(), reject: vi.fn() }))
vi.mock("../../../api/curator", () => ({ commitCuratorDraft: api.commit }))
vi.mock("../../../api/knowledge", () => ({
  acceptKnowledgeRelationSuggestion: api.accept,
  rejectKnowledgeRelationSuggestion: api.reject,
}))

const artifact = {
  artifact_id: "knowledge-1", version: 1, producer_task_id: "curator-1", kind: "knowledge_draft", scope_ref: "scope-1", content: {}, evidence_refs: [],
  source_coverage: { complete: true, covered_refs: ["paper-a"], missing_refs: [], notes: [] },
  verification_status: "passed", verification_report: { issues: [] },
  notes: [], items: [{ draft_id: "item-1" }],
  relation_proposals: [{ proposal_id: "proposal-1", source_draft_or_item_id: "item-1", target_draft_or_item_id: "item-2", relation_type: "supports", rationale: "Evidence", evidence_ids: ["ev-1"] }],
} satisfies AgentArtifact

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe("GraphProposalPanel", () => {
  it("separates generated, saved, and accepted states", async () => {
    api.commit.mockResolvedValue({ operation_id: "op-1", artifact_id: "knowledge-1", artifact_version: 1, workspace_id: "ws-1", status: "completed", replayed: false, results: [{ target_key: "relation:proposal-1", target_kind: "relation_proposal", status: "committed", object_id: "suggestion-1", error_code: "", message: "" }] })
    api.accept.mockResolvedValue({})
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><GraphProposalPanel artifact={artifact} scope={{ scope_ref: "scope-1" }} /></QueryClientProvider>)
    expect(screen.getByText(/已生成，待保存/)).not.toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "保存笔记与建议" }))
    expect(await screen.findByText(/已保存，待决策/)).not.toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "接受" }))
    await waitFor(() => expect(api.accept).toHaveBeenCalledWith("suggestion-1"))
    expect(screen.getByRole("status").textContent).toContain("已接受")
  })
})
