import type {
  AgentKnowledgeContext,
  AgentKnowledgeCardContext as ApiKnowledgeCardContext,
} from "../../../api/agent"
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

export interface KnowledgeAgentCardContext {
  itemId: string
  itemType: string
  title: string
  summary: string
  documentId?: string | null
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
  cards?: KnowledgeAgentCardContext[]
  relations?: KnowledgeAgentRelationContext[]
  canvas?: KnowledgeAgentCanvasContext
}

export interface ResolvedKnowledgeAgentContext {
  sourceText: string
  context: ReadingContextFields
  documentIds: string[]
  relations: KnowledgeAgentRelationContext[]
  canvas: KnowledgeAgentCanvasContext | null
  knowledgeContext: AgentKnowledgeContext
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

function itemDocumentId(item: KnowledgeItem): string {
  return item.resource_document_id?.trim() || metadataText(item, "document_id")
}

function fallbackCard(item: KnowledgeItem): KnowledgeAgentCardContext {
  return {
    itemId: item.item_id,
    itemType: item.item_type,
    title: item.title,
    summary: item.summary,
    documentId: itemDocumentId(item),
  }
}

function apiCard(card: KnowledgeAgentCardContext): ApiKnowledgeCardContext {
  return {
    item_id: card.itemId,
    item_type: card.itemType,
    title: card.title,
    summary: card.summary,
    document_id: card.documentId?.trim() ?? "",
  }
}

function buildStructuredKnowledgeContext(
  context: KnowledgeAgentContext,
  relations: KnowledgeAgentRelationContext[],
  canvas: KnowledgeAgentCanvasContext | null,
): AgentKnowledgeContext {
  const cards = (context.cards?.length ? context.cards : [fallbackCard(context.item)]).slice(0, 60)
  return {
    canvas: canvas
      ? {
          board_id: canvas.boardId,
          board_name: canvas.boardName,
          scope_label: canvas.scopeLabel,
        }
      : null,
    cards: cards.map(apiCard),
    relations: relations.slice(0, 60).map((relation) => ({
      relation_id: relation.relationId,
      source_item_id: relation.sourceItemId,
      source_title: relation.sourceTitle,
      target_item_id: relation.targetItemId,
      target_title: relation.targetTitle,
      relation_type: relation.relationType,
      label: relation.label?.trim() ?? "",
      origin: relation.origin,
      confidence: relation.confidence ?? null,
    })),
  }
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
  const relations = (context.relations ?? []).slice(0, 60)
  const canvas = context.canvas ?? null
  const metadataDocumentId = metadataText(item, "document_id")
  const documentIds = [
    ...(context.documentIds ?? []),
    ...(context.cards ?? []).map((card) => card.documentId?.trim() ?? ""),
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
    knowledgeContext: buildStructuredKnowledgeContext(context, relations, canvas),
  }
}
