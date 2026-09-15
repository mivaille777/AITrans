import { createContext } from "react"

import type { KnowledgeAction } from "./KnowledgeActionMenu"
import type { KnowledgeItem } from "./knowledge-types"
import type { KnowledgeWorkspaceEvent } from "./knowledge-workspace-events"

export type KnowledgeWorkspaceState = {
  selectedKnowledgeItem: KnowledgeItem | null
  selectedKnowledgeIds: string[]
  lastEvent: KnowledgeWorkspaceEvent | null
}

export const initialKnowledgeWorkspaceState: KnowledgeWorkspaceState = {
  selectedKnowledgeItem: null,
  selectedKnowledgeIds: [],
  lastEvent: null,
}

export type KnowledgeWorkspaceContextValue = KnowledgeWorkspaceState & {
  selectKnowledgeItem: (item: KnowledgeItem | null) => void
  setSelectedKnowledgeIds: (ids: string[]) => void
  clearSelection: () => void
  runKnowledgeAction: (
    action: KnowledgeAction,
    item?: KnowledgeItem | null,
  ) => KnowledgeWorkspaceEvent | null
}

export const KnowledgeWorkspaceContext = createContext<KnowledgeWorkspaceContextValue | null>(null)
