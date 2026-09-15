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

  const commitUndo = useCallback(() => {
    setUndoStack((current) => {
      const entry = current.at(-1)
      if (!entry) return current
      setRedoStack((redo) => [...redo, entry])
      return current.slice(0, -1)
    })
  }, [])

  const commitRedo = useCallback(() => {
    setRedoStack((current) => {
      const entry = current.at(-1)
      if (!entry) return current
      setUndoStack((undo) => [...undo, entry])
      return current.slice(0, -1)
    })
  }, [])

  const clear = useCallback(() => {
    setUndoStack([])
    setRedoStack([])
  }, [])

  return useMemo(() => ({
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    undoEntry: undoStack.at(-1) ?? null,
    redoEntry: redoStack.at(-1) ?? null,
    undoLabel: undoStack.at(-1)?.label ?? "",
    redoLabel: redoStack.at(-1)?.label ?? "",
    record,
    commitUndo,
    commitRedo,
    clear,
  }), [clear, commitRedo, commitUndo, record, redoStack, undoStack])
}
