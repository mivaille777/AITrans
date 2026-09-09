import { createContext, type ReactNode, useContext, useMemo, useState } from "react"

import type { KnowledgeItem } from "./knowledge-types"

type WorkspaceContextValue = {
  selectedKnowledgeItem: KnowledgeItem | null
  selectedKnowledgeIds: string[]
  selectKnowledgeItem: (item: KnowledgeItem | null) => void
  setSelectedKnowledgeIds: (ids: string[]) => void
}

const KnowledgeWorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function KnowledgeWorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedKnowledgeItem, setSelectedKnowledgeItem] = useState<KnowledgeItem | null>(null)
  const [selectedKnowledgeIds, setSelectedKnowledgeIds] = useState<string[]>([])

  const value = useMemo(() => ({
    selectedKnowledgeItem,
    selectedKnowledgeIds,
    selectKnowledgeItem: setSelectedKnowledgeItem,
    setSelectedKnowledgeIds,
  }), [selectedKnowledgeItem, selectedKnowledgeIds])

  return (
    <KnowledgeWorkspaceContext.Provider value={value}>
      {children}
    </KnowledgeWorkspaceContext.Provider>
  )
}

export function useKnowledgeWorkspaceContext() {
  const context = useContext(KnowledgeWorkspaceContext)
  if (!context) throw new Error("useKnowledgeWorkspaceContext must be used inside KnowledgeWorkspaceProvider")
  return context
}
