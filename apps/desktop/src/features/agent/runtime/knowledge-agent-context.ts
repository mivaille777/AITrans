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
  const sourceText = item.summary.trim() || item.title.trim()
  return {
    sourceText,
    context: {
      resource_url: buildKnowledgeResourceUrl(context),
      resource_title: item.title,
      section_heading: `Knowledge card · ${item.item_type}`,
      context_before: "",
      context_after: "",
      source_kind: "knowledge_card",
    },
    documentIds: item.resource_document_id ? [item.resource_document_id] : [],
  }
}
