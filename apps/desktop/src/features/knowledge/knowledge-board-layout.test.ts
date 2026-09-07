import { describe, expect, it } from "vitest"

import {
  boardEdgePath,
  clampBoardZoom,
  fitBoardNodes,
  screenToBoard,
} from "./knowledge-board-layout"
import type { KnowledgeBoardNode } from "./knowledge-types"

function node(itemId: string, x: number, y: number, width = 240, height = 150): KnowledgeBoardNode {
  return {
    board_id: "board",
    item_id: itemId,
    x,
    y,
    width,
    height,
    collapsed: false,
    z_index: 0,
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
  }
}

describe("knowledge board layout", () => {
  it("converts screen coordinates through the persisted board viewport", () => {
    expect(
      screenToBoard(
        260,
        190,
        { left: 10, top: 20, width: 800, height: 600 },
        { x: 50, y: 30, zoom: 2 },
      ),
    ).toEqual({ x: 100, y: 70 })
  })

  it("fits multiple board nodes inside the canvas", () => {
    const viewport = fitBoardNodes([node("a", 0, 0), node("b", 600, 300)], 1000, 700)
    expect(viewport.zoom).toBeGreaterThanOrEqual(0.35)
    expect(viewport.zoom).toBeLessThanOrEqual(1.35)
    expect(Number.isFinite(viewport.x)).toBe(true)
    expect(Number.isFinite(viewport.y)).toBe(true)
  })

  it("creates a directed bezier edge between card centers", () => {
    const edge = boardEdgePath(node("a", 10, 20, 200, 100), node("b", 420, 200, 200, 100))
    expect(edge.path).toContain("M 210 70")
    expect(edge.path).toContain("420 250")
  })

  it("clamps board zoom to safe interaction limits", () => {
    expect(clampBoardZoom(0.1)).toBe(0.35)
    expect(clampBoardZoom(3)).toBe(2.2)
  })
})
