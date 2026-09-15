import type { BadgeTone } from "../../shared/ui/Badge"
import type { KnowledgeDocument, KnowledgeDocumentStatus } from "./knowledge-types"

const ACTIVE_STATUSES = new Set<KnowledgeDocumentStatus>([
  "pending",
  "parsing",
  "chunking",
  "embedding",
  "indexing",
])

export function isKnowledgeDocumentActive(status: KnowledgeDocumentStatus): boolean {
  return ACTIVE_STATUSES.has(status)
}

export function hasActiveKnowledgeDocuments(documents: KnowledgeDocument[]): boolean {
  return documents.some((document) => isKnowledgeDocumentActive(document.status))
}

export function knowledgeStatusLabel(status: KnowledgeDocumentStatus): string {
  if (status === "ready") return "Ready"
  if (status === "failed") return "Failed"
  if (status === "pending") return "Pending"
  return status.charAt(0).toUpperCase() + status.slice(1)
}

export function knowledgeStatusTone(status: KnowledgeDocumentStatus): BadgeTone {
  if (status === "ready") return "success"
  if (status === "failed") return "danger"
  return "info"
}
