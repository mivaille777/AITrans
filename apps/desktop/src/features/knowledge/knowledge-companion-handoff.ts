import type { CompanionHandoffRequest } from "../../api/types"
import type { KnowledgeItem } from "./knowledge-types"

interface KnowledgeChatHandoffOptions {
  sourceLanguage?: string
  targetLanguage?: string
  suggestedPrompt?: string
}

function metadataText(item: KnowledgeItem, key: string): string {
  const value = item.metadata?.[key]
  return typeof value === "string" ? value.trim() : ""
}

function collectDocumentIds(item: KnowledgeItem): string[] {
  const values: string[] = []
  if (item.resource_document_id) values.push(item.resource_document_id)

  const metadataDocumentId = metadataText(item, "document_id")
  if (metadataDocumentId) values.push(metadataDocumentId)

  const sources = item.metadata?.sources
  if (Array.isArray(sources)) {
    for (const source of sources) {
      if (!source || typeof source !== "object") continue
      const documentId = "document_id" in source && typeof source.document_id === "string"
        ? source.document_id.trim()
        : ""
      if (documentId) values.push(documentId)
    }
  }
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].slice(0, 100)
}

function defaultPrompt(item: KnowledgeItem): string {
  switch (item.item_type) {
    case "evidence":
      return "Analyze this evidence in its paper context and explain how it supports or challenges the current research question."
    case "insight":
      return "Develop this insight using its linked evidence and the relevant indexed document context."
    case "question":
      return "Investigate this research question using the linked knowledge and relevant indexed documents."
    case "highlight":
      return "Explain why this highlighted passage matters in the context of the source paper."
    default:
      return "Continue reasoning from this knowledge card and its grounded source context."
  }
}

function sourceKind(item: KnowledgeItem): string {
  if (item.item_type === "evidence") return "knowledge_evidence"
  if (item.item_type === "insight") return "knowledge_insight"
  if (item.item_type === "question") return "knowledge_question"
  return "knowledge_card"
}

export function buildKnowledgeCompanionHandoff(
  item: KnowledgeItem,
  options: KnowledgeChatHandoffOptions = {},
): CompanionHandoffRequest {
  const selectionText = metadataText(item, "selection_text")
  const sourceText = item.item_type === "insight"
    ? item.summary.trim() || item.title.trim()
    : selectionText || item.summary.trim() || item.title.trim()
  const documentIds = collectDocumentIds(item)

  return {
    source_text: sourceText,
    translated_text: "",
    source_language: options.sourceLanguage?.trim() || "auto",
    target_language: options.targetLanguage?.trim() || "zh-CN",
    resource_url: `knowledge-item://${encodeURIComponent(item.item_id)}`,
    resource_title: item.title,
    section_heading: metadataText(item, "section_heading") || `Knowledge card · ${item.item_type}`,
    context_before: metadataText(item, "context_before"),
    context_after: metadataText(item, "context_after"),
    source_kind: sourceKind(item),
    source_event_id: item.item_id,
    ai_content: item.item_type === "insight" ? item.summary : "",
    ai_action: "knowledge_context",
    suggested_prompt: options.suggestedPrompt?.trim() || defaultPrompt(item),
    context_id: `knowledge:${item.item_id}`,
    knowledge_document_ids: documentIds,
    research_source_ids: [],
  }
}

export function knowledgeCardDocumentIds(item: KnowledgeItem): string[] {
  return collectDocumentIds(item)
}
