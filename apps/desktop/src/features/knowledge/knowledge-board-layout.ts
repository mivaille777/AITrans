import type { KnowledgeBoardNode } from "./knowledge-types"

export interface BoardViewport {
  x: number
  y: number
  zoom: number
}

export interface BoardBounds {
  left: number
  top: number
  width: number
  height: number
}

export const DEFAULT_BOARD_VIEWPORT: BoardViewport = { x: 64, y: 64, zoom: 1 }

export function clampBoardZoom(value: number): number {
  return Math.min(2.2, Math.max(0.35, value))
}

export function screenToBoard(
  clientX: number,
  clientY: number,
  bounds: BoardBounds,
  viewport: BoardViewport,
): { x: number; y: number } {
  return {
    x: (clientX - bounds.left - viewport.x) / viewport.zoom,
    y: (clientY - bounds.top - viewport.y) / viewport.zoom,
  }
}

export function fitBoardNodes(
  nodes: KnowledgeBoardNode[],
  canvasWidth: number,
  canvasHeight: number,
  padding = 80,
): BoardViewport {
  if (nodes.length === 0 || canvasWidth <= 0 || canvasHeight <= 0) {
    return DEFAULT_BOARD_VIEWPORT
  }

  const minX = Math.min(...nodes.map((node) => node.x))
  const minY = Math.min(...nodes.map((node) => node.y))
  const maxX = Math.max(...nodes.map((node) => node.x + node.width))
  const maxY = Math.max(...nodes.map((node) => node.y + node.height))
  const contentWidth = Math.max(1, maxX - minX)
  const contentHeight = Math.max(1, maxY - minY)
  const zoom = clampBoardZoom(
    Math.min(
      (canvasWidth - padding * 2) / contentWidth,
      (canvasHeight - padding * 2) / contentHeight,
      1.35,
    ),
  )

  return {
    zoom,
    x: (canvasWidth - contentWidth * zoom) / 2 - minX * zoom,
    y: (canvasHeight - contentHeight * zoom) / 2 - minY * zoom,
  }
}

interface EdgeAnchor {
  x: number
  y: number
  axis: "horizontal" | "vertical"
  direction: -1 | 1
}

function nodeCenter(node: KnowledgeBoardNode) {
  return {
    x: node.x + node.width / 2,
    y: node.y + node.height / 2,
  }
}

function relationAnchors(
  source: KnowledgeBoardNode,
  target: KnowledgeBoardNode,
): { source: EdgeAnchor; target: EdgeAnchor } {
  const sourceCenter = nodeCenter(source)
  const targetCenter = nodeCenter(target)
  const dx = targetCenter.x - sourceCenter.x
  const dy = targetCenter.y - sourceCenter.y

  const horizontalGap = dx >= 0
    ? target.x - (source.x + source.width)
    : source.x - (target.x + target.width)
  const verticalGap = dy >= 0
    ? target.y - (source.y + source.height)
    : source.y - (target.y + target.height)

  // Prefer a genuinely separated axis first. If cards overlap on both axes,
  // choose the dominant center displacement so the curve still exits outward
  // instead of doubling back through either card.
  const useHorizontal = horizontalGap >= 0
    ? verticalGap < 0 || horizontalGap >= verticalGap
    : verticalGap < 0 && Math.abs(dx) >= Math.abs(dy)

  if (useHorizontal) {
    if (dx >= 0) {
      return {
        source: { x: source.x + source.width, y: sourceCenter.y, axis: "horizontal", direction: 1 },
        target: { x: target.x, y: targetCenter.y, axis: "horizontal", direction: -1 },
      }
    }
    return {
      source: { x: source.x, y: sourceCenter.y, axis: "horizontal", direction: -1 },
      target: { x: target.x + target.width, y: targetCenter.y, axis: "horizontal", direction: 1 },
    }
  }

  if (dy >= 0) {
    return {
      source: { x: sourceCenter.x, y: source.y + source.height, axis: "vertical", direction: 1 },
      target: { x: targetCenter.x, y: target.y, axis: "vertical", direction: -1 },
    }
  }
  return {
    source: { x: sourceCenter.x, y: source.y, axis: "vertical", direction: -1 },
    target: { x: targetCenter.x, y: target.y + target.height, axis: "vertical", direction: 1 },
  }
}

export function boardEdgePath(
  source: KnowledgeBoardNode,
  target: KnowledgeBoardNode,
): { path: string; labelX: number; labelY: number } {
  const anchors = relationAnchors(source, target)
  const start = anchors.source
  const end = anchors.target

  if (start.axis === "horizontal") {
    const distance = Math.abs(end.x - start.x)
    const bend = Math.max(42, Math.min(150, distance * 0.45))
    const control1X = start.x + bend * start.direction
    const control2X = end.x + bend * end.direction
    return {
      path: `M ${start.x} ${start.y} C ${control1X} ${start.y}, ${control2X} ${end.y}, ${end.x} ${end.y}`,
      labelX: (start.x + 3 * control1X + 3 * control2X + end.x) / 8,
      labelY: (start.y + 3 * start.y + 3 * end.y + end.y) / 8,
    }
  }

  const distance = Math.abs(end.y - start.y)
  const bend = Math.max(42, Math.min(150, distance * 0.45))
  const control1Y = start.y + bend * start.direction
  const control2Y = end.y + bend * end.direction
  return {
    path: `M ${start.x} ${start.y} C ${start.x} ${control1Y}, ${end.x} ${control2Y}, ${end.x} ${end.y}`,
    labelX: (start.x + 3 * start.x + 3 * end.x + end.x) / 8,
    labelY: (start.y + 3 * control1Y + 3 * control2Y + end.y) / 8,
  }
}
