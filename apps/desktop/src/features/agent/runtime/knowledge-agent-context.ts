import type { ReadingContextFields } from "../../../api/types"
import type { KnowledgeItem } from "../../knowledge/knowledge-types"
import type { KnowledgeWritebackIntent } from "../../knowledge/knowledge-workspace-events"

export interface KnowledgeAgentContext {
  item: KnowledgeItem
  writeback: KnowledgeWritebackIntent | null
  sourceText?: string
  readingContext?: ReadingContextFields
  documentIds?: string[]
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
  const readingContext = context.readingContext
  const selectionText = metadataText(item, "selection_text")
  const sourceText = context.sourceText?.trim()
    || selectionText
    || item.summary.trim()
    || item.title.trim()
  const metadataDocumentId = metadataText(item, "document_id")
  const documentIds = [
    ...(context.documentIds ?? []),
    item.resource_document_id?.trim() ?? "",
    metadataDocumentId,
  ].filter(Boolean)
  const sectionHeading = readingContext?.section_heading?.trim()
    || metadataText(item, "section_heading")
  const evidenceGrounded = item.item_type === "evidence" || Boolean(selectionText)

  return {
    sourceText,
    context: {
      resource_url: buildKnowledgeResourceUrl(context),
      resource_title: readingContext?.resource_title?.trim() || item.title,
      section_heading: sectionHeading || `Knowledge card · ${item.item_type}`,
      context_before: readingContext?.context_before?.trim() || metadataText(item, "context_before"),
      context_after: readingContext?.context_after?.trim() || metadataText(item, "context_after"),
      source_kind: readingContext?.source_kind?.trim()
        || (evidenceGrounded ? "knowledge_evidence" : "knowledge_card"),
    },
    documentIds: [...new Set(documentIds)],
  }
}
