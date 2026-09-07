import type {
  KnowledgeDocumentOutlineSection,
  KnowledgeDocumentSection,
  KnowledgeItemType,
} from "./knowledge-types"

export interface PaperSelectionContext {
  text: string
  contextBefore: string
  contextAfter: string
}

export type DerivedPaperCardType = Extract<KnowledgeItemType, "note" | "concept" | "highlight">
export type DerivedPaperRelationType = "derived_from" | "reading_note"

export function resolvePaperReaderSectionId(
  sections: KnowledgeDocumentOutlineSection[],
  preferredSectionId: string,
): string {
  const preferred = preferredSectionId.trim()
  if (preferred && sections.some((section) => section.section_id === preferred)) return preferred
  return sections[0]?.section_id ?? ""
}

export function paperPageLabel(pageStart: number | null, pageEnd: number | null): string {
  if (pageStart == null && pageEnd == null) return "Page —"
  if (pageStart != null && pageEnd != null && pageEnd !== pageStart) return `Pages ${pageStart}–${pageEnd}`
  return `Page ${pageStart ?? pageEnd}`
}

export function buildPaperSelectionContext(
  section: KnowledgeDocumentSection,
  selectedText: string,
  radius = 700,
): PaperSelectionContext {
  const text = selectedText.trim()
  if (!text) return { text: "", contextBefore: "", contextAfter: "" }

  const index = section.text.indexOf(text)
  if (index < 0) return { text, contextBefore: "", contextAfter: "" }

  return {
    text,
    contextBefore: section.text.slice(Math.max(0, index - radius), index).trim(),
    contextAfter: section.text.slice(index + text.length, index + text.length + radius).trim(),
  }
}

export function buildSelectionCardTitle(
  selectedText: string,
  fallback: string,
  maxLength = 72,
): string {
  const normalized = selectedText.replace(/\s+/g, " ").trim()
  if (!normalized) return fallback
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`
}

export function resolveDerivedPaperRelationType(
  _itemType: DerivedPaperCardType,
  requested?: DerivedPaperRelationType,
): DerivedPaperRelationType {
  return requested ?? "derived_from"
}
