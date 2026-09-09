import { useState } from "react"

import type { KnowledgeItem } from "./knowledge-types"

export function useKnowledgeWorkspace() {
  const [selectedKnowledgeItem, setSelectedKnowledgeItem] = useState<KnowledgeItem | null>(null)
  const [selectedKnowledgeIds, setSelectedKnowledgeIds] = useState<string[]>([])

  return {
    selectedKnowledgeItem,
    setSelectedKnowledgeItem,
    selectedKnowledgeIds,
    setSelectedKnowledgeIds,
  }
}
