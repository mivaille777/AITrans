import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react"

import type { KnowledgeAction } from "./KnowledgeActionMenu"
import { dispatchKnowledgeAction } from "./knowledge-action-dispatcher"
import type { KnowledgeItem } from "./knowledge-types"
import {
  emitKnowledgeWorkspaceEvent,
  type KnowledgeWorkspaceEvent,
} from "./knowledge-workspace-events"

type WorkspaceContextValue = {
  selectedKnowledgeItem: KnowledgeItem | null
  selectedKnowledgeIds: string[]
  lastEvent: KnowledgeWorkspaceEvent | null
  selectKnowledgeItem: (item: KnowledgeItem | null) => void
  setSelectedKnowledgeIds: (ids: string[]) => void
  clearSelection: () => void
  runKnowledgeAction: (
    action: KnowledgeAction,
    item?: KnowledgeItem | null,
  ) => KnowledgeWorkspaceEvent | null
}

const KnowledgeWorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function KnowledgeWorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedKnowledgeItem, setSelectedKnowledgeItem] = useState<KnowledgeItem | null>(null)
  const [selectedKnowledgeIds, setSelectedKnowledgeIds] = useState<string[]>([])
  const [lastEvent, setLastEvent] = useState<KnowledgeWorkspaceEvent | null>(null)

  const clearSelection = useCallback(() => {
    setSelectedKnowledgeIds([])
    setSelectedKnowledgeItem(null)
  }, [])

  const runKnowledgeAction = useCallback((
    action: KnowledgeAction,
    item?: KnowledgeItem | null,
  ) => {
    const target = item ?? selectedKnowledgeItem
    if (!target) return null

    const request = dispatchKnowledgeAction(action, { item: target })
    if (!request) return null

    const event = emitKnowledgeWorkspaceEvent(request)
    setLastEvent(event)
    return event
  }, [selectedKnowledgeItem])

  const value = useMemo(() => ({
    selectedKnowledgeItem,
    selectedKnowledgeIds,
    lastEvent,
    selectKnowledgeItem: setSelectedKnowledgeItem,
    setSelectedKnowledgeIds,
    clearSelection,
    runKnowledgeAction,
  }), [
    selectedKnowledgeItem,
    selectedKnowledgeIds,
    lastEvent,
    clearSelection,
    runKnowledgeAction,
  ])

  return (
    <KnowledgeWorkspaceContext.Provider value={value}>
      {children}
    </KnowledgeWorkspaceContext.Provider>
  )
}

export function useKnowledgeWorkspaceContext() {
  const context = useContext(KnowledgeWorkspaceContext)
  if (!context) {
    throw new Error("useKnowledgeWorkspaceContext must be used inside KnowledgeWorkspaceProvider")
  }
  return context
}
