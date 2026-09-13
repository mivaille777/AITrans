import type { ReadingContextFields } from "../../../api/types"
import type { KnowledgeItem } from "../../knowledge/knowledge-types"
import type { KnowledgeWritebackIntent } from "../../knowledge/knowledge-workspace-events"

export interface KnowledgeAgentContext {
  item: KnowledgeItem
  writeback: KnowledgeWritebackIntent | null
}

export interface ResolvedKnowledgeAgentContext {
  sourceText: string
  context: ReadingContextFields
  documentIds: string[]
}

function metadataText(item: KnowledgeItem, key: string): string {
  const value = item.metadata?.[key]
  return typeof value === "string" ? value.trim() : ""
}

function buildKnowledgeResourceUrl(context: KnowledgeAgentContext): string {
  const params = new URLSearchParams()
  if (context.writeback) {
    params.set("type", context.writeback.itemType)
    params.set("operation", context.writeback.operation)
    params.set("relation", context.writeback.relationType)
  }
  const query = params.toString()
  return `knowledge-item://${encodeURIComponent(context.item.item_id)}${query ? `?${query}` : ""}`
}

export function resolveKnowledgeAgentContext(
  context: KnowledgeAgentContext | null | undefined,
): ResolvedKnowledgeAgentContext | null {
  if (!context) return null

  const item = context.item
  const selectionText = metadataText(item, "selection_text")
  const sourceText = selectionText || item.summary.trim() || item.title.trim()
  const metadataDocumentId = metadataText(item, "document_id")
  const documentId = item.resource_document_id?.trim() || metadataDocumentId
  const sectionHeading = metadataText(item, "section_heading")
  const evidenceGrounded = item.item_type === "evidence" || Boolean(selectionText)

  return {
    sourceText,
    context: {
      resource_url: buildKnowledgeResourceUrl(context),
      resource_title: item.title,
      section_heading: sectionHeading || `Knowledge card · ${item.item_type}`,
      context_before: metadataText(item, "context_before"),
      context_after: metadataText(item, "context_after"),
      source_kind: evidenceGrounded ? "knowledge_evidence" : "knowledge_card",
    },
    documentIds: documentId ? [documentId] : [],
  }
}
