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

export function boardEdgePath(
  source: KnowledgeBoardNode,
  target: KnowledgeBoardNode,
): { path: string; labelX: number; labelY: number } {
  const sourceX = source.x + source.width
  const sourceY = source.y + source.height / 2
  const targetX = target.x
  const targetY = target.y + target.height / 2
  const bend = Math.max(70, Math.abs(targetX - sourceX) * 0.45)
  const control1 = sourceX + bend
  const control2 = targetX - bend

  return {
    path: `M ${sourceX} ${sourceY} C ${control1} ${sourceY}, ${control2} ${targetY}, ${targetX} ${targetY}`,
    labelX: (sourceX + targetX) / 2,
    labelY: (sourceY + targetY) / 2,
  }
}
