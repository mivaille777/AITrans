import type {
  KnowledgeCardMetadata,
  KnowledgeCardProvenance,
  KnowledgeEvidenceSource,
  KnowledgeItem,
  KnowledgeItemType,
  KnowledgeUserItemType,
} from "./knowledge-types"

export const KNOWLEDGE_CARD_TYPE_LABELS: Record<KnowledgeItemType, string> = {
  paper: "Paper",
  note: "Note",
  concept: "Concept",
  highlight: "Highlight",
  evidence: "Evidence",
  insight: "Insight",
  question: "Question",
  document: "Document",
  web: "Web",
}

export const CREATABLE_KNOWLEDGE_CARD_TYPES: Array<KnowledgeUserItemType | "paper"> = [
  "note",
  "concept",
  "highlight",
  "evidence",
  "insight",
  "question",
  "paper",
]

export function knowledgeCardLabel(type: KnowledgeItemType): string {
  return KNOWLEDGE_CARD_TYPE_LABELS[type]
}

export function knowledgeCardConfidence(item: Pick<KnowledgeItem, "metadata">): number | null {
  const value = item.metadata.confidence
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : null
}

export function knowledgeCardSources(item: Pick<KnowledgeItem, "metadata">): KnowledgeEvidenceSource[] {
  return Array.isArray(item.metadata.sources)
    ? item.metadata.sources.filter(isEvidenceSource)
    : []
}

export function knowledgeCardProvenance(item: Pick<KnowledgeItem, "metadata">): KnowledgeCardProvenance | null {
  const value = item.metadata.provenance
  if (!value || typeof value !== "object") return null
  const createdBy = value.created_by
  if (!["user", "agent", "imported", "system"].includes(createdBy)) return null
  return value
}

export function newKnowledgeCardMetadata(createdBy: KnowledgeCardProvenance["created_by"] = "user"): KnowledgeCardMetadata {
  return {
    provenance: { created_by: createdBy },
  }
}

function isEvidenceSource(value: unknown): value is KnowledgeEvidenceSource {
  if (!value || typeof value !== "object") return false
  const source = value as Partial<KnowledgeEvidenceSource>
  return typeof source.document_id === "string" && source.document_id.length > 0
}
