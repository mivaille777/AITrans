// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { KnowledgeItem } from "../knowledge/knowledge-types"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeResearchBridgePanel from "./KnowledgeResearchBridgePanel"

const api = vi.hoisted(() => ({
  listKnowledgeItems: vi.fn(),
}))

vi.mock("../knowledge/knowledge-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../knowledge/knowledge-api")>(),
  ...api,
}))

vi.mock("../../api/companion", () => ({
  createCompanionHandoff: vi.fn(),
}))

const workspace = {
  sourceLanguage: "auto",
  targetLanguage: "zh-CN",
  researchRetrievalScope: { knowledgeDocumentIds: [], researchSourceIds: [] },
} as unknown as TranslationWorkspaceController

function card(index: number): KnowledgeItem {
  return {
    item_id: `item-${index}`,
    item_type: "evidence",
    title: `Evidence card ${index}`,
    summary: `Summary ${index}`,
    resource_document_id: "document-1",
    source_uri: "file:///paper.pdf",
    metadata: { document_id: "document-1", page_start: index },
    created_at: `2026-09-${String(index).padStart(2, "0")}T00:00:00Z`,
    updated_at: `2026-09-${String(index).padStart(2, "0")}T00:00:00Z`,
  }
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <KnowledgeResearchBridgePanel workspace={workspace} />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("KnowledgeResearchBridgePanel", () => {
  it("keeps the Research page focused on three recent cards until the user expands the preview", async () => {
    api.listKnowledgeItems.mockResolvedValue({ total: 7, items: Array.from({ length: 7 }, (_, index) => card(index + 1)) })
    renderPanel()

    expect(await screen.findByText("Evidence card 7")).not.toBeNull()
    expect(screen.getByText("Evidence card 6")).not.toBeNull()
    expect(screen.getByText("Evidence card 5")).not.toBeNull()
    expect(screen.queryByText("Evidence card 4")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Show all 7" }))
    expect(await screen.findByText("Evidence card 3")).not.toBeNull()
    expect(screen.getByText("Evidence card 1")).not.toBeNull()
    expect(screen.getByRole("button", { name: "Show preview" })).not.toBeNull()
  })
})
