import { useCallback, useMemo, useState } from "react"

import type { KnowledgeBoardNode } from "./knowledge-types"

export type KnowledgeBoardNodeSnapshot = Pick<
  KnowledgeBoardNode,
  "item_id" | "x" | "y" | "width" | "height" | "collapsed" | "z_index"
>

export interface KnowledgeBoardHistoryEntry {
  label: string
  itemId: string
  before: KnowledgeBoardNodeSnapshot | null
  after: KnowledgeBoardNodeSnapshot | null
}

export function nodeSnapshot(node: KnowledgeBoardNode): KnowledgeBoardNodeSnapshot {
  return {
    item_id: node.item_id,
    x: node.x,
    y: node.y,
    width: node.width,
    height: node.height,
    collapsed: node.collapsed,
    z_index: node.z_index,
  }
}

export function sameNodeSnapshot(
  left: KnowledgeBoardNodeSnapshot | null,
  right: KnowledgeBoardNodeSnapshot | null,
): boolean {
  if (left === right) return true
  if (!left || !right) return false
  return left.item_id === right.item_id
    && left.x === right.x
    && left.y === right.y
    && left.width === right.width
    && left.height === right.height
    && left.collapsed === right.collapsed
    && left.z_index === right.z_index
}

export function useKnowledgeBoardHistory(limit = 60) {
  const [undoStack, setUndoStack] = useState<KnowledgeBoardHistoryEntry[]>([])
  const [redoStack, setRedoStack] = useState<KnowledgeBoardHistoryEntry[]>([])

  const record = useCallback((entry: KnowledgeBoardHistoryEntry) => {
    if (sameNodeSnapshot(entry.before, entry.after)) return
    setUndoStack((current) => [...current.slice(-(limit - 1)), entry])
    setRedoStack([])
  }, [limit])

  const takeUndo = useCallback(() => {
    let selected: KnowledgeBoardHistoryEntry | null = null
    setUndoStack((current) => {
      if (current.length === 0) return current
      selected = current[current.length - 1]
      return current.slice(0, -1)
    })
    if (selected) setRedoStack((current) => [...current, selected as KnowledgeBoardHistoryEntry])
    return selected
  }, [])

  const takeRedo = useCallback(() => {
    let selected: KnowledgeBoardHistoryEntry | null = null
    setRedoStack((current) => {
      if (current.length === 0) return current
      selected = current[current.length - 1]
      return current.slice(0, -1)
    })
    if (selected) setUndoStack((current) => [...current, selected as KnowledgeBoardHistoryEntry])
    return selected
  }, [])

  const clear = useCallback(() => {
    setUndoStack([])
    setRedoStack([])
  }, [])

  return useMemo(() => ({
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    undoLabel: undoStack.at(-1)?.label ?? "",
    redoLabel: redoStack.at(-1)?.label ?? "",
    record,
    takeUndo,
    takeRedo,
    clear,
  }), [clear, record, redoStack, takeRedo, takeUndo, undoStack])
}
