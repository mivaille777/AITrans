import { create } from "zustand"

export type KnowledgeNode = {
  id: string
  title: string
  type: "paper" | "concept" | "note"
  summary?: string
}

export type KnowledgeEdge = {
  source: string
  target: string
  relation: string
  confidence: number
}

type KnowledgeCanvasState = {
  nodes: KnowledgeNode[]
  edges: KnowledgeEdge[]
  selectedNode?: KnowledgeNode
  setGraph: (nodes: KnowledgeNode[], edges: KnowledgeEdge[]) => void
  selectNode: (node?: KnowledgeNode) => void
}

export const useKnowledgeCanvasStore = create<KnowledgeCanvasState>((set) => ({
  nodes: [],
  edges: [],
  selectedNode: undefined,
  setGraph: (nodes, edges) => set({ nodes, edges }),
  selectNode: (selectedNode) => set({ selectedNode }),
}))
