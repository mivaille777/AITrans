// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import type { ConversationListResponse } from "../../api/types"
import ConversationHistoryPanel from "./ConversationHistoryPanel"

const { getConversations, renameConversation, deleteConversation } = vi.hoisted(() => ({
  getConversations: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
}))

vi.mock("../../api/conversations", () => ({
  getConversations,
  renameConversation,
  deleteConversation,
}))

const conversationList: ConversationListResponse = {
  conversations: [
    {
      conversation_id: "conversation-1",
      session_id: "session-1",
      title: "Design systems for research",
      created_at: "2026-09-17T08:00:00Z",
      updated_at: "2026-09-17T10:24:00Z",
      provider: "local",
      model: "deepseek-v4-flash",
      context_mode: "reading",
      resource_title: "Continue from reading context…",
      section_heading: "Current reading selection",
      source_kind: "pdf",
    },
  ],
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ConversationHistoryPanel
          activeConversationId=""
          hasCurrentReading={false}
          onOpen={vi.fn()}
          onUseCurrentReading={vi.fn()}
          onNewGeneralConversation={vi.fn()}
          onDeletedActive={vi.fn()}
        />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe("ConversationHistoryPanel compact interaction", () => {
  beforeEach(() => {
    getConversations.mockResolvedValue(conversationList)
    renameConversation.mockResolvedValue(conversationList.conversations[0])
    deleteConversation.mockResolvedValue({ deleted: true, conversation_id: "conversation-1" })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("keeps list rows compact and moves actions into the context menu", async () => {
    const user = userEvent.setup()
    renderPanel()

    const title = await screen.findByText("Design systems for research")
    expect(screen.queryByText("Reading")).toBeNull()
    expect(screen.queryByText("General")).toBeNull()
    expect(screen.queryByText("deepseek-v4-flash")).toBeNull()
    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull()

    await user.pointer({ target: title, keys: "[MouseRight]" })

    expect(screen.getByRole("menu")).not.toBeNull()
    expect(screen.getByRole("menuitem", { name: /Rename/ })).not.toBeNull()
    expect(screen.getByRole("menuitem", { name: "Permanently delete" })).not.toBeNull()

    await user.click(screen.getByRole("menuitem", { name: /Rename/ }))
    expect(screen.getByDisplayValue("Design systems for research")).not.toBeNull()
  })
})
