import type { ReadingContextFields } from "../../../api/types"
import type { KnowledgeItem, KnowledgeRelationOrigin } from "../../knowledge/knowledge-types"
import type { KnowledgeWritebackIntent } from "../../knowledge/knowledge-workspace-events"

export interface KnowledgeAgentRelationContext {
  relationId: string
  sourceItemId: string
  sourceTitle: string
  targetItemId: string
  targetTitle: string
  relationType: string
  label?: string
  origin: KnowledgeRelationOrigin
  confidence?: number | null
}

export interface KnowledgeAgentCanvasContext {
  boardId: string
  boardName: string
  scopeLabel: string
}

export interface KnowledgeAgentContext {
  item: KnowledgeItem
  writeback: KnowledgeWritebackIntent | null
  sourceText?: string
  readingContext?: ReadingContextFields
  documentIds?: string[]
  relations?: KnowledgeAgentRelationContext[]
  canvas?: KnowledgeAgentCanvasContext
}

export interface ResolvedKnowledgeAgentContext {
  sourceText: string
  context: ReadingContextFields
  documentIds: string[]
  relations: KnowledgeAgentRelationContext[]
  canvas: KnowledgeAgentCanvasContext | null
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

function relationContextText(
  relations: KnowledgeAgentRelationContext[],
  canvas: KnowledgeAgentCanvasContext | null,
): string {
  if (relations.length === 0 && !canvas) return ""

  const lines = [
    "Canvas relationship context:",
    "- These relations describe user/AI knowledge organization, not independent factual evidence.",
    "- origin=manual means the user explicitly authored or accepted the relation; it does not by itself prove the scientific claim.",
    "- Use relations to navigate and compare cards. For factual conclusions, rely on linked Evidence/Paper content or retrieved document evidence.",
  ]
  if (canvas) {
    lines.push(`- Canvas: ${canvas.boardName} (${canvas.scopeLabel}; id=${canvas.boardId})`)
  }
  if (relations.length === 0) {
    lines.push("- No explicit canonical relations are attached to this scope.")
    return lines.join("\n")
  }

  lines.push("Canonical relations:")
  relations.slice(0, 60).forEach((relation, index) => {
    const details = [
      `origin=${relation.origin}`,
      relation.label?.trim() ? `label=${relation.label.trim()}` : "",
      relation.confidence == null ? "" : `confidence=${relation.confidence}`,
    ].filter(Boolean).join("; ")
    lines.push(
      `[R${index + 1}] ${relation.sourceTitle} (${relation.sourceItemId}) --${relation.relationType}--> ${relation.targetTitle} (${relation.targetItemId})${details ? ` | ${details}` : ""}`,
    )
  })
  return lines.join("\n")
}

export function resolveKnowledgeAgentContext(
  context: KnowledgeAgentContext | null | undefined,
): ResolvedKnowledgeAgentContext | null {
  if (!context) return null

  const item = context.item
  const readingContext = context.readingContext
  const selectionText = metadataText(item, "selection_text")
  const baseSourceText = context.sourceText?.trim()
    || selectionText
    || item.summary.trim()
    || item.title.trim()
  const relations = (context.relations ?? []).slice(0, 60)
  const canvas = context.canvas ?? null
  const relationText = relationContextText(relations, canvas)
  const sourceText = relationText ? `${baseSourceText}\n\n${relationText}` : baseSourceText
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
    relations,
    canvas,
  }
}
