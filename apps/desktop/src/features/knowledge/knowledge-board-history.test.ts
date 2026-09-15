import { describe, expect, it } from "vitest"

import { nodeSnapshot, sameNodeSnapshot } from "./knowledge-board-history"
import type { KnowledgeBoardNode } from "./knowledge-types"

function node(overrides: Partial<KnowledgeBoardNode> = {}): KnowledgeBoardNode {
  return {
    board_id: "kb_test",
    item_id: "item_a",
    x: 10,
    y: 20,
    width: 248,
    height: 156,
    collapsed: false,
    z_index: 1,
    created_at: "2026-09-14T00:00:00Z",
    updated_at: "2026-09-14T00:00:00Z",
    ...overrides,
  }
}

describe("knowledge board history snapshots", () => {
  it("keeps only persisted layout fields", () => {
    expect(nodeSnapshot(node())).toEqual({
      item_id: "item_a",
      x: 10,
      y: 20,
      width: 248,
      height: 156,
      collapsed: false,
      z_index: 1,
    })
  })

  it("detects move and resize changes", () => {
    const before = nodeSnapshot(node())
    const moved = nodeSnapshot(node({ x: 40 }))
    const resized = nodeSnapshot(node({ width: 320, height: 220 }))

    expect(sameNodeSnapshot(before, before)).toBe(true)
    expect(sameNodeSnapshot(before, moved)).toBe(false)
    expect(sameNodeSnapshot(before, resized)).toBe(false)
  })

  it("treats add and remove snapshots as history changes", () => {
    const snapshot = nodeSnapshot(node())
    expect(sameNodeSnapshot(null, snapshot)).toBe(false)
    expect(sameNodeSnapshot(snapshot, null)).toBe(false)
    expect(sameNodeSnapshot(null, null)).toBe(true)
  })
})
