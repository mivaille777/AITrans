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

export type PaperReaderSelectionSource = "text" | "pdf"

export interface PaperReaderSelectionTarget {
  source: PaperReaderSelectionSource
  text: string
  pageNumber?: number | null
}

export type DerivedPaperCardType = Extract<
  KnowledgeItemType,
  "note" | "concept" | "highlight" | "evidence"
>
export type DerivedPaperRelationType = "derived_from" | "reading_note"

export function resolvePaperReaderSectionId(
  sections: KnowledgeDocumentOutlineSection[],
  preferredSectionId: string,
): string {
  const preferred = preferredSectionId.trim()
  if (preferred && sections.some((section) => section.section_id === preferred)) return preferred
  return sections[0]?.section_id ?? ""
}

export function resolvePaperReaderSectionForPage(
  sections: KnowledgeDocumentOutlineSection[],
  pageNumber: number,
): KnowledgeDocumentOutlineSection | null {
  if (!sections.length || !Number.isFinite(pageNumber) || pageNumber < 1) return null
  const page = Math.round(pageNumber)
  const containing = sections.filter((section) => {
    const start = section.page_start
    const end = section.page_end ?? start
    return start != null && end != null && page >= start && page <= end
  })

  if (containing.length) {
    return [...containing].sort((left, right) => {
      if (left.reference_section !== right.reference_section) return left.reference_section ? 1 : -1
      if (left.synthetic !== right.synthetic) return left.synthetic ? 1 : -1
      const leftSpan = (left.page_end ?? left.page_start ?? page) - (left.page_start ?? page)
      const rightSpan = (right.page_end ?? right.page_start ?? page) - (right.page_start ?? page)
      if (leftSpan !== rightSpan) return leftSpan - rightSpan
      return right.level - left.level
    })[0] ?? null
  }

  const before = sections
    .filter((section) => section.page_start != null && section.page_start <= page)
    .sort((left, right) => (right.page_start ?? 0) - (left.page_start ?? 0))[0]
  if (before) return before

  return sections
    .filter((section) => section.page_start != null)
    .sort((left, right) => (left.page_start ?? Number.MAX_SAFE_INTEGER) - (right.page_start ?? Number.MAX_SAFE_INTEGER))[0]
    ?? sections[0]
    ?? null
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
