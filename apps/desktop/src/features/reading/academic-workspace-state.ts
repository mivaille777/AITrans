import type {
  KnowledgeDocument,
  KnowledgeDocumentOutlineSection,
  KnowledgeDocumentSection,
} from "../knowledge/knowledge-types"

export const ACADEMIC_ACTIVE_DOCUMENT_KEY = "aitrans.academic.activeDocumentId"
export const MAX_ACADEMIC_AGENT_CHARS = 18_000

export function resolveActiveAcademicDocumentId(
  documents: KnowledgeDocument[],
  preferredId: string,
): string {
  const preferred = preferredId.trim()
  if (preferred && documents.some((document) => document.document_id === preferred)) {
    return preferred
  }
  return (
    documents.find((document) => document.status === "ready")?.document_id ??
    documents[0]?.document_id ??
    ""
  )
}

export function resolveActiveAcademicSectionId(
  sections: KnowledgeDocumentOutlineSection[],
  preferredId: string,
): string {
  const preferred = preferredId.trim()
  if (preferred && sections.some((section) => section.section_id === preferred)) {
    return preferred
  }
  return (
    sections.find((section) => !section.synthetic && !section.reference_section)?.section_id ??
    sections[0]?.section_id ??
    ""
  )
}

export function academicPageLabel(
  pageStart: number | null,
  pageEnd: number | null,
): string {
  if (!pageStart) return "Page —"
  if (!pageEnd || pageEnd === pageStart) return `Page ${pageStart}`
  return `Pages ${pageStart}–${pageEnd}`
}

export function buildAcademicAgentText(section: KnowledgeDocumentSection): {
  text: string
  truncated: boolean
} {
  const source = section.text.trim()
  if (source.length <= MAX_ACADEMIC_AGENT_CHARS) {
    return { text: source, truncated: section.truncated }
  }
  return {
    text: source.slice(0, MAX_ACADEMIC_AGENT_CHARS).trimEnd(),
    truncated: true,
  }
}
