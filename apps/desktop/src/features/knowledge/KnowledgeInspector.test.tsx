// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import KnowledgeInspector from "./KnowledgeInspector"
import type { KnowledgeItem } from "./knowledge-types"

const item: KnowledgeItem = {
  item_id: "note-1",
  item_type: "note",
  title: "Planning notes",
  summary: "Notes captured from a paper.",
  resource_document_id: null,
  source_uri: "",
  metadata: {},
  created_at: "2026-09-09T00:00:00Z",
  updated_at: "2026-09-09T00:00:00Z",
}

afterEach(cleanup)

describe("KnowledgeInspector", () => {
  it("shows an empty selection state", () => {
    render(<KnowledgeInspector item={null} />)
    expect(screen.getByText(/select one card/i)).toBeInTheDocument()
  })

  it("renders selected knowledge and emits AI actions", async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()

    render(
      <KnowledgeInspector
        item={item}
        relationCount={2}
        lastEventType="KNOWLEDGE_SUMMARIZE_REQUEST"
        onAction={onAction}
      />,
    )

    expect(screen.getByText("Planning notes")).toBeInTheDocument()
    expect(screen.getByText("2")).toBeInTheDocument()
    expect(screen.getByText(/knowledge summarize request/i)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Summarize" }))
    expect(onAction).toHaveBeenCalledWith("summarize")
  })
})
