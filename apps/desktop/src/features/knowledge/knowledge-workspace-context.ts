import type { KnowledgeItem } from "./knowledge-types"

export type KnowledgeWorkspaceEvent = {
  type: string
  item?: KnowledgeItem
}

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
