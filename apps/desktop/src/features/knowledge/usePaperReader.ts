import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { translateText } from "../../api/translation"
import { queryKeys } from "../../shared/query/query-keys"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import {
  createKnowledgeItem,
  createKnowledgeRelation,
  deleteKnowledgeItem,
  getKnowledgeDocumentOutline,
  getKnowledgeDocumentPreviewUrl,
  getKnowledgeDocumentSection,
  listKnowledgeRelations,
  updateKnowledgeItem,
} from "./knowledge-api"
import {
  buildPaperSelectionContext,
  buildSelectionCardTitle,
  resolveDerivedPaperRelationType,
  resolvePaperReaderSectionForPage,
  resolvePaperReaderSectionId,
  type DerivedPaperCardType,
  type DerivedPaperRelationType,
  type PaperReaderSelectionTarget,
} from "./paper-reader-state"
import type {
  KnowledgeDocumentSection,
  KnowledgeItem,
  KnowledgeRelation,
} from "./knowledge-types"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

const READER_CARD_TEXT_LIMIT = 50_000
const READER_AGENT_TEXT_LIMIT = 12_000
const READER_TRANSLATION_TEXT_LIMIT = 8_000
const EMPTY_ITEMS: KnowledgeItem[] = []
const READER_QUERY_STALE_TIME = 5 * 60 * 1000

interface DerivedCardRequest extends PaperReaderSelectionTarget {
  itemType: DerivedPaperCardType
  relationType?: DerivedPaperRelationType
}

interface LinkedCardRequest {
  itemType: DerivedPaperCardType
  title: string
  summary: string
  relationType: DerivedPaperRelationType
  metadata?: Record<string, unknown>
}

interface TranslationNoteRequest {
  sourceText: string
  translatedText: string
}

interface SectionPreference {
  paperItemId: string
  sectionId: string
}

export function usePaperReader(
  paperItemId: string,
  library: KnowledgeLibraryController,
  workspace: TranslationWorkspaceController,
) {
  const queryClient = useQueryClient()
  const [sectionPreference, setSectionPreference] = useState<SectionPreference>({
    paperItemId,
    sectionId: "",
  })
  const preferredSectionId = sectionPreference.paperItemId === paperItemId
    ? sectionPreference.sectionId
    : ""
  const items = library.itemsQuery.data?.items ?? EMPTY_ITEMS
  const documents = library.documentsQuery.data?.documents ?? []
  const paper = items.find((item) => item.item_id === paperItemId) ?? null
  const document = paper?.resource_document_id
    ? documents.find((item) => item.document_id === paper.resource_document_id) ?? null
    : null
  const previewUrl = document?.source_type === "pdf"
    ? getKnowledgeDocumentPreviewUrl(document.document_id)
    : ""

  const outlineQuery = useQuery({
    queryKey: ["knowledge", "paper-reader", "outline", document?.document_id ?? "none"],
    queryFn: () => getKnowledgeDocumentOutline(document?.document_id as string),
    enabled: Boolean(document?.document_id && document.status === "ready"),
    staleTime: READER_QUERY_STALE_TIME,
  })

  const sections = outlineQuery.data?.sections ?? []
  const activeSectionId = resolvePaperReaderSectionId(sections, preferredSectionId)
  const activeOutlineSection = sections.find((section) => section.section_id === activeSectionId) ?? null
  const sectionQuery = useQuery({
    queryKey: ["knowledge", "paper-reader", "section", document?.document_id ?? "none", activeSectionId],
    queryFn: () => getKnowledgeDocumentSection(document?.document_id as string, activeSectionId),
    enabled: Boolean(document?.document_id && activeSectionId && document.status === "ready"),
    staleTime: READER_QUERY_STALE_TIME,
  })

  const relationsQuery = useQuery({
    queryKey: queryKeys.knowledge.relations,
    queryFn: () => listKnowledgeRelations(),
  })

  const itemById = useMemo(
    () => new Map(items.map((item) => [item.item_id, item] as const)),
    [items],
  )
  const linked = useMemo(() => {
    if (!paper) return []
    return (relationsQuery.data?.relations ?? [])
      .filter((relation) => relation.source_item_id === paper.item_id || relation.target_item_id === paper.item_id)
      .map((relation) => {
        const otherId = relation.source_item_id === paper.item_id
          ? relation.target_item_id
          : relation.source_item_id
        return { relation, item: itemById.get(otherId) ?? null }
      })
      .filter((entry): entry is { relation: KnowledgeRelation; item: KnowledgeItem } => Boolean(entry.item))
  }, [itemById, paper, relationsQuery.data?.relations])

  const readingNote = linked.find(
    ({ relation, item }) => relation.relation_type === "reading_note" && item.item_type === "note",
  )?.item ?? null

  const refreshKnowledge = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.items }),
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.relations }),
    ])
  }

  async function resolveSelectionSection(
    selection: PaperReaderSelectionTarget,
  ): Promise<KnowledgeDocumentSection | null> {
    if (!document) return null
    if (selection.source !== "pdf" || !selection.pageNumber) return sectionQuery.data ?? null

    const outlineSection = resolvePaperReaderSectionForPage(sections, selection.pageNumber)
    if (!outlineSection) return sectionQuery.data ?? null
    if (sectionQuery.data?.section_id === outlineSection.section_id) return sectionQuery.data

    return queryClient.fetchQuery({
      queryKey: ["knowledge", "paper-reader", "section", document.document_id, outlineSection.section_id],
      queryFn: () => getKnowledgeDocumentSection(document.document_id, outlineSection.section_id),
      staleTime: READER_QUERY_STALE_TIME,
    })
  }

  async function createLinkedCard({
    itemType,
    title,
    summary,
    relationType,
    metadata,
  }: LinkedCardRequest): Promise<KnowledgeItem> {
    if (!paper || !document) throw new Error("This paper is not attached to an indexed document.")
    const section = sectionQuery.data
    const card = await createKnowledgeItem({
      item_type: itemType,
      title,
      summary,
      source_uri: paper.source_uri,
      metadata: {
        paper_item_id: paper.item_id,
        document_id: document.document_id,
        section_id: section?.section_id ?? "",
        section_heading: section?.heading ?? "",
        page_start: section?.page_start ?? null,
        page_end: section?.page_end ?? null,
        provenance: "paper_reader",
        relation_type: relationType,
        ...metadata,
      },
    })
    try {
      await createKnowledgeRelation({
        source_item_id: card.item_id,
        target_item_id: paper.item_id,
        relation_type: relationType,
        origin: "manual",
      })
    } catch (error) {
      await deleteKnowledgeItem(card.item_id).catch(() => undefined)
      throw error
    }
    return card
  }

  const createDerivedMutation = useMutation({
    mutationFn: async ({ itemType, text, relationType, source, pageNumber }: DerivedCardRequest) => {
      if (!paper || !document) throw new Error("This paper is not attached to an indexed document.")
      const selection: PaperReaderSelectionTarget = { source, text, pageNumber }
      const selectionSection = await resolveSelectionSection(selection)
      const normalizedText = text.trim().slice(0, READER_CARD_TEXT_LIMIT)
      const selectionContext = selectionSection
        ? buildPaperSelectionContext(selectionSection, normalizedText)
        : { text: normalizedText, contextBefore: "", contextAfter: "" }
      const resolvedRelationType = resolveDerivedPaperRelationType(itemType, relationType)
      const titleFallback = resolvedRelationType === "reading_note"
        ? `Reading note · ${paper.title}`
        : itemType === "highlight"
          ? "Paper highlight"
          : itemType === "concept"
            ? "Paper concept"
            : itemType === "evidence"
              ? "Paper evidence"
              : "Paper note"
      const pdfPageNumber = source === "pdf" && pageNumber ? Math.max(1, Math.round(pageNumber)) : null
      return createLinkedCard({
        itemType,
        title: buildSelectionCardTitle(normalizedText, titleFallback),
        summary: normalizedText,
        relationType: resolvedRelationType,
        metadata: {
          selection_text: selectionContext.text,
          selection_source: source,
          pdf_page_number: pdfPageNumber,
          context_before: selectionContext.contextBefore,
          context_after: selectionContext.contextAfter,
          section_id: selectionSection?.section_id ?? "",
          section_heading: selectionSection?.heading ?? "",
          page_start: selectionSection?.page_start ?? pdfPageNumber,
          page_end: selectionSection?.page_end ?? pdfPageNumber,
          provenance: source === "pdf" ? "paper_reader_pdf_selection" : "paper_reader_selection",
          evidence_kind: itemType === "evidence"
            ? source === "pdf" ? "paper_pdf_selection" : "paper_selection"
            : undefined,
          sources: itemType === "evidence" ? [{
            document_id: document.document_id,
            quote: selectionContext.text,
            page: pdfPageNumber ?? selectionSection?.page_start ?? undefined,
            section: selectionSection?.heading ?? "",
            source_uri: document.source_uri,
          }] : undefined,
        },
      })
    },
    onSuccess: () => void refreshKnowledge(),
  })

  const updateReadingNoteMutation = useMutation({
    mutationFn: async (summary: string) => {
      if (!readingNote) throw new Error("Create a reading note before editing it.")
      return updateKnowledgeItem(readingNote.item_id, {
        summary: summary.slice(0, READER_CARD_TEXT_LIMIT),
      })
    },
    onSuccess: () => void refreshKnowledge(),
  })

  const translationMutation = useMutation({
    mutationFn: (text: string) => translateText({
      source_text: text.trim().slice(0, READER_TRANSLATION_TEXT_LIMIT),
      source_language: workspace.sourceLanguage,
      target_language: workspace.targetLanguage,
    }),
  })

  const saveTranslationAsNoteMutation = useMutation({
    mutationFn: async ({ sourceText, translatedText }: TranslationNoteRequest) => {
      if (!paper) throw new Error("Paper context is unavailable.")
      const boundedSource = sourceText.trim().slice(0, READER_TRANSLATION_TEXT_LIMIT)
      const boundedTranslation = translatedText.trim().slice(0, READER_CARD_TEXT_LIMIT)
      if (!boundedTranslation) throw new Error("There is no translation to save.")
      return createLinkedCard({
        itemType: "note",
        title: `Translation · ${buildSelectionCardTitle(boundedSource, paper.title, 52)}`,
        summary: boundedTranslation,
        relationType: "derived_from",
        metadata: {
          provenance: "paper_reader_translation",
          translation_source_text: boundedSource,
          source_language: workspace.sourceLanguage,
          target_language: workspace.targetLanguage,
        },
      })
    },
    onSuccess: () => void refreshKnowledge(),
  })

  function selectSection(sectionId: string) {
    setSectionPreference({
      paperItemId,
      sectionId: sectionId.trim(),
    })
  }

  async function attachSelectionToAgent(selection: PaperReaderSelectionTarget) {
    if (!paper || !document) return false
    const boundedSelection = selection.text.trim().slice(0, READER_AGENT_TEXT_LIMIT)
    if (!boundedSelection) return false
    const selectionSection = await resolveSelectionSection({ ...selection, text: boundedSelection })
    if (!selectionSection) return false
    const context = buildPaperSelectionContext(selectionSection, boundedSelection)
    if (!context.text) return false
    const pdfPageNumber = selection.source === "pdf" && selection.pageNumber
      ? Math.max(1, Math.round(selection.pageNumber))
      : null
    workspace.useAcademicReadingContext({
      context_id: pdfPageNumber
        ? `knowledge:${document.document_id}:${selectionSection.section_id}:pdf:${pdfPageNumber}:selection`
        : `knowledge:${document.document_id}:${selectionSection.section_id}:selection`,
      document_id: document.document_id,
      text: context.text,
      resource_url: document.source_uri,
      resource_title: paper.title,
      section_heading: pdfPageNumber
        ? `${selectionSection.heading || "Document section"} · PDF page ${pdfPageNumber}`
        : selectionSection.heading,
      context_before: context.contextBefore,
      context_after: context.contextAfter,
      source_kind: "knowledge_document",
    })
    return true
  }

  function attachSectionToAgent() {
    if (!paper || !document || !sectionQuery.data) return false
    const section = sectionQuery.data
    const boundedText = section.text.trim().slice(0, READER_AGENT_TEXT_LIMIT)
    if (!boundedText) return false
    const boundedByReader = boundedText.length < section.text.trim().length
    workspace.useAcademicReadingContext({
      context_id: `knowledge:${document.document_id}:${section.section_id}`,
      document_id: document.document_id,
      text: boundedText,
      resource_url: document.source_uri,
      resource_title: paper.title,
      section_heading: section.heading,
      context_before: "",
      context_after: section.truncated || boundedByReader ? "This section exceeds the bounded Agent reading context; only the leading portion is attached." : "",
      source_kind: "knowledge_document",
    })
    return true
  }

  return {
    paper,
    document,
    previewUrl,
    outlineQuery,
    sectionQuery,
    relationsQuery,
    sections,
    activeSectionId,
    activeOutlineSection,
    linked,
    readingNote,
    createDerivedMutation,
    updateReadingNoteMutation,
    translationMutation,
    saveTranslationAsNoteMutation,
    selectSection,
    attachSelectionToAgent,
    attachSectionToAgent,
  }
}