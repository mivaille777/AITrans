export type KnowledgeV2CardType =
  | "concept"
  | "evidence"
  | "insight"
  | "question"

export type KnowledgeV2RelationType =
  | "similar"
  | "support"
  | "cites"
  | "extends"
  | "causes"
  | "hierarchy"
  | "evolves"

export interface KnowledgeV2Evidence {
  id: string
  documentId: string
  chunkId?: string
  quote: string
  page?: number
  section?: string
}

export interface KnowledgeV2Relation {
  id: string
  sourceCardId: string
  targetCardId: string
  type: KnowledgeV2RelationType
  confidence: number
  createdBy: "agent" | "user"
  evidenceIds: string[]
}

export interface KnowledgeV2Card {
  id: string
  type: KnowledgeV2CardType
  title: string
  summary: string
  content: Record<string, unknown>
  confidence: number
  sources: KnowledgeV2Evidence[]
  relations: KnowledgeV2Relation[]
  createdAt: string
  updatedAt: string
}

export interface KnowledgeV2Graph {
  nodes: KnowledgeV2Card[]
  edges: KnowledgeV2Relation[]
}
