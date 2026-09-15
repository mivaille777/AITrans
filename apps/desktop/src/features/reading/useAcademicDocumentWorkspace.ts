import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import {
  getKnowledgeDocumentOutline,
  getKnowledgeDocumentSection,
} from "../knowledge/knowledge-api"
import { useKnowledgeLibrary } from "../knowledge/useKnowledgeLibrary"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import {
  ACADEMIC_ACTIVE_DOCUMENT_KEY,
  buildAcademicAgentText,
  resolveActiveAcademicDocumentId,
  resolveActiveAcademicSectionId,
} from "./academic-workspace-state"

function readPersistedDocumentId(): string {
  if (typeof window === "undefined") return ""
  return window.localStorage.getItem(ACADEMIC_ACTIVE_DOCUMENT_KEY) ?? ""
}

function persistDocumentId(documentId: string) {
  if (typeof window === "undefined") return
  if (documentId) {
    window.localStorage.setItem(ACADEMIC_ACTIVE_DOCUMENT_KEY, documentId)
  } else {
    window.localStorage.removeItem(ACADEMIC_ACTIVE_DOCUMENT_KEY)
  }
}

export function useAcademicDocumentWorkspace(workspace: TranslationWorkspaceController) {
  const library = useKnowledgeLibrary()
  const [preferredDocumentId, setPreferredDocumentId] = useState(readPersistedDocumentId)
  const [preferredSectionId, setPreferredSectionId] = useState("")
  const documents = library.documentsQuery.data?.documents ?? []
  const activeDocumentId = resolveActiveAcademicDocumentId(documents, preferredDocumentId)
  const activeDocument = documents.find((item) => item.document_id === activeDocumentId) ?? null

  const outlineQuery = useQuery({
    queryKey: ["knowledge", "academic-outline", activeDocumentId],
    queryFn: () => getKnowledgeDocumentOutline(activeDocumentId),
    enabled: Boolean(activeDocumentId && activeDocument?.status === "ready"),
    staleTime: 5 * 60 * 1000,
  })

  const sections = outlineQuery.data?.sections ?? []
  const activeSectionId = resolveActiveAcademicSectionId(sections, preferredSectionId)
  const activeSection = sections.find((section) => section.section_id === activeSectionId) ?? null
  const sectionQuery = useQuery({
    queryKey: ["knowledge", "academic-section", activeDocumentId, activeSectionId],
    queryFn: () => getKnowledgeDocumentSection(activeDocumentId, activeSectionId),
    enabled: Boolean(activeDocumentId && activeSectionId && activeDocument?.status === "ready"),
    staleTime: 5 * 60 * 1000,
  })

  function selectDocument(documentId: string) {
    const normalized = documentId.trim()
    setPreferredDocumentId(normalized)
    setPreferredSectionId("")
    persistDocumentId(normalized)
  }

  function selectSection(sectionId: string) {
    setPreferredSectionId(sectionId.trim())
  }

  function attachSectionToAgent() {
    const section = sectionQuery.data
    if (!section || !activeDocument) return false
    const bounded = buildAcademicAgentText(section)
    if (!bounded.text) return false
    workspace.useAcademicReadingContext({
      context_id: `knowledge:${activeDocument.document_id}:${section.section_id}`,
      document_id: activeDocument.document_id,
      text: bounded.text,
      resource_url: activeDocument.source_uri,
      resource_title: activeDocument.title || outlineQuery.data?.title || "Academic document",
      section_heading: section.heading || section.section_path.at(-1) || "",
      context_before: "",
      context_after: bounded.truncated
        ? "The selected section exceeds the bounded Agent reading context; only the leading portion is attached."
        : "",
      source_kind: "knowledge_document",
    })
    return true
  }

  return {
    library,
    documents,
    activeDocumentId,
    activeDocument,
    outlineQuery,
    sections,
    activeSectionId,
    activeSection,
    sectionQuery,
    selectDocument,
    selectSection,
    attachSectionToAgent,
    attachedContext: workspace.academicReadingContext,
  }
}

export type AcademicDocumentWorkspaceController = ReturnType<
  typeof useAcademicDocumentWorkspace
>
