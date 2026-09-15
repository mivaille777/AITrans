// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ComponentProps } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import KnowledgeBoardCanvas from "./KnowledgeBoardCanvas"
import type { KnowledgeBoardNode, KnowledgeItem, KnowledgeRelation } from "./knowledge-types"

const now = "2026-09-15T00:00:00Z"

const source: KnowledgeItem = {
  item_id: "source-1",
  item_type: "insight",
  title: "LLM refinement insight",
  summary: "Bounded local refinement insight.",
  resource_document_id: null,
  source_uri: "",
  metadata: {},
  created_at: now,
  updated_at: now,
}

const target: KnowledgeItem = {
  item_id: "target-1",
  item_type: "evidence",
  title: "PID tuning evidence",
  summary: "Evidence from the paper.",
  resource_document_id: null,
  source_uri: "",
  metadata: {},
  created_at: now,
  updated_at: now,
}

const nodes: KnowledgeBoardNode[] = [
  { board_id: "board-1", item_id: source.item_id, x: 40, y: 80, width: 248, height: 156, collapsed: false, z_index: 1, created_at: now, updated_at: now },
  { board_id: "board-1", item_id: target.item_id, x: 380, y: 80, width: 248, height: 156, collapsed: false, z_index: 2, created_at: now, updated_at: now },
]

const relation: KnowledgeRelation = {
  relation_id: "relation-1",
  source_item_id: source.item_id,
  target_item_id: target.item_id,
  relation_type: "supports",
  label: "Supports the claim",
  origin: "manual",
  confidence: null,
  metadata: {},
  created_at: now,
  updated_at: now,
}

function renderCanvas(overrides: Partial<ComponentProps<typeof KnowledgeBoardCanvas>> = {}) {
  const props: ComponentProps<typeof KnowledgeBoardCanvas> = {
    items: [source, target],
    nodes,
    relations: [],
    selectedItemIds: [],
    onSelectionChange: vi.fn(),
    onRelationSelectionChange: vi.fn(),
    onAddNode: vi.fn(),
    onPersistNode: vi.fn(),
    onRemoveNode: vi.fn(),
    onLinkRequest: vi.fn(),
    ...overrides,
  }
  const rendered = render(<KnowledgeBoardCanvas {...props} />)
  return { ...rendered, props }
}

afterEach(cleanup)

describe("KnowledgeBoardCanvas relations", () => {
  it("supports the accessible click-to-connect fallback", async () => {
    const user = userEvent.setup()
    const onLinkRequest = vi.fn()
    renderCanvas({ onLinkRequest })

    await user.click(screen.getByRole("button", { name: "Connect LLM refinement insight" }))
    await user.click(screen.getByText("PID tuning evidence"))

    expect(onLinkRequest).toHaveBeenCalledWith("source-1", "target-1")
  })

  it("lets the user select a canonical edge for inspection", () => {
    const onRelationSelectionChange = vi.fn()
    const { container } = renderCanvas({
      relations: [relation],
      onRelationSelectionChange,
    })

    const edgeGroup = container.querySelector('[data-knowledge-relation="relation-1"]')
    const hitTarget = edgeGroup?.querySelector('path[stroke="transparent"]')
    expect(hitTarget).toBeTruthy()
    fireEvent.click(hitTarget as Element)

    expect(onRelationSelectionChange).toHaveBeenCalledWith("relation-1")
  })
})
