import {
  ArrowUpDown,
  BookOpenCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  GripVertical,
  Highlighter,
  Languages,
  Lightbulb,
  Link2,
  ListTree,
  LoaderCircle,
  Monitor,
  MoreHorizontal,
  Plus,
  Quote,
  RotateCcw,
  Search,
  Sparkles,
  StickyNote,
  Tag,
  Trash2,
  X,
} from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { desktop } from "../../desktop"
import { getKnowledgeDocumentPreviewUrl } from "../knowledge/knowledge-api"
import type {
  KnowledgeDocument,
  KnowledgeItem,
  KnowledgeUserItemType,
} from "../knowledge/knowledge-types"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import PdfReaderSurface, { type PdfReaderSelection } from "./PdfReaderSurface"
import { resolveReadingPaperId } from "./reading-navigation"
import { useAcademicDocumentWorkspace } from "./useAcademicDocumentWorkspace"

const DOCUMENT_ORDER_KEY = "aitrans.reading.documentOrder"
const DOCUMENT_ACCESS_KEY = "aitrans.reading.documentAccess"

type DocumentFilter = "all" | "pdf" | "word" | "markdown" | "text" | "other"
type SortMode = "manual" | "name" | "type" | "accessed"

type ReaderSelection = {
  source: "text" | "pdf"
  text: string
  pageNumber?: number | null
}

export default function UnifiedReadingWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const controller = useAcademicDocumentWorkspace(workspace)
  const library = controller.library
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedPaperId = resolveReadingPaperId(searchParams)
  const items = library.itemsQuery.data?.items ?? []
  const documents = controller.documents

  const resourceItemsByDocumentId = new Map<string, KnowledgeItem>()
  for (const item of items) {
    if (
      item.resource_document_id &&
      (item.item_type === "paper" || item.item_type === "document")
    ) {
      resourceItemsByDocumentId.set(item.resource_document_id, item)
    }
  }

  const [documentsCollapsed, setDocumentsCollapsed] = useState(false)
  const [outlineCollapsed, setOutlineCollapsed] = useState(false)
  const [documentFilter, setDocumentFilter] = useState<DocumentFilter>("all")
  const [documentSearch, setDocumentSearch] = useState("")
  const [outlineSearch, setOutlineSearch] = useState("")
  const [sortMode, setSortMode] = useState<SortMode>("manual")
  const [sortOpen, setSortOpen] = useState(false)
  const [manualOrder, setManualOrder] = useState<string[]>(readStringArray(DOCUMENT_ORDER_KEY))
  const [lastAccessed, setLastAccessed] = useState<Record<string, string>>(
    readStringRecord(DOCUMENT_ACCESS_KEY),
  )
  const [draggedDocumentId, setDraggedDocumentId] = useState("")
  const [showTrash, setShowTrash] = useState(false)
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<ReaderSelection | null>(null)
  const [tagDraft, setTagDraft] = useState("")
  const [liveReadingOpen, setLiveReadingOpen] = useState(false)
  const [statusMessage, setStatusMessage] = useState("")
  const articleRef = useRef<HTMLDivElement | null>(null)

  const trashedDocumentIds = new Set<string>()
  for (const document of documents) {
    const item = resourceItemsByDocumentId.get(document.document_id)
    if (item?.metadata.trashed || item?.metadata.trashed_at) {
      trashedDocumentIds.add(document.document_id)
    }
  }

  const activePool = documents.filter(
    (document) => showTrash === trashedDocumentIds.has(document.document_id),
  )
  const orderedDocuments = orderDocuments(
    activePool.filter((document) => {
      if (!matchesDocumentFilter(document, documentFilter)) return false
      const needle = documentSearch.trim().toLowerCase()
      if (!needle) return true
      return (
        document.title.toLowerCase().includes(needle) ||
        document.source_type.toLowerCase().includes(needle) ||
        document.source_uri.toLowerCase().includes(needle)
      )
    }),
    sortMode,
    manualOrder,
    lastAccessed,
  )

  const activeDocument = controller.activeDocument
  const activeResourceItem = activeDocument
    ? resourceItemsByDocumentId.get(activeDocument.document_id) ?? null
    : null
  const activeSection = controller.sectionQuery.data
  const currentTags = activeResourceItem && Array.isArray(activeResourceItem.metadata.tags)
    ? activeResourceItem.metadata.tags.filter((tag): tag is string => typeof tag === "string")
    : []

  const outlineSections = filterOutlineSections(
    controller.sections,
    outlineSearch,
    collapsedSections,
  )

  useEffect(() => {
    if (!requestedPaperId || !items.length) return
    const requestedItem = items.find((item) => item.item_id === requestedPaperId)
    const documentId = requestedItem?.resource_document_id
    if (documentId && documentId !== controller.activeDocumentId) {
      controller.selectDocument(documentId)
    }
  }, [controller, items, requestedPaperId])

  useEffect(() => {
    if (showTrash) return
    const visibleDocuments = documents.filter(
      (document) => !trashedDocumentIds.has(document.document_id),
    )
    if (!visibleDocuments.length) return
    if (
      !controller.activeDocumentId ||
      trashedDocumentIds.has(controller.activeDocumentId)
    ) {
      controller.selectDocument(visibleDocuments[0].document_id)
    }
  }, [controller, documents, showTrash, trashedDocumentIds])

  useEffect(() => {
    if (!activeDocument) return
    setSelection(null)
    setTagDraft("")
    setLastAccessed((current) => {
      const next = {
        ...current,
        [activeDocument.document_id]: new Date().toISOString(),
      }
      writeJson(DOCUMENT_ACCESS_KEY, next)
      return next
    })
  }, [activeDocument])

  function selectDocument(documentId: string) {
    controller.selectDocument(documentId)
    setSelection(null)
    const item = resourceItemsByDocumentId.get(documentId)
    const next = new URLSearchParams(searchParams)
    if (item?.item_type === "paper") next.set("paper", item.item_id)
    else next.delete("paper")
    setSearchParams(next, { replace: true })
  }

  function importDocument() {
    library.addMutation.mutate(undefined, {
      onSuccess: (result) => {
        if (!result) return
        setStatusMessage("Document imported and added to Reading.")
        controller.selectDocument(result.document.document_id)
      },
    })
  }

  function moveDocument(dragId: string, targetId: string) {
    if (!dragId || !targetId || dragId === targetId) return
    const allIds = documents.map((document) => document.document_id)
    const merged = [
      ...manualOrder.filter((id) => allIds.includes(id)),
      ...allIds.filter((id) => !manualOrder.includes(id)),
    ]
    const from = merged.indexOf(dragId)
    const to = merged.indexOf(targetId)
    if (from < 0 || to < 0) return
    merged.splice(from, 1)
    merged.splice(to, 0, dragId)
    setManualOrder(merged)
    setSortMode("manual")
    writeJson(DOCUMENT_ORDER_KEY, merged)
  }

  function moveToTrash(documentId: string) {
    const item = resourceItemsByDocumentId.get(documentId)
    if (!item) {
      setStatusMessage("This document is still syncing with Knowledge Library. Try again in a moment.")
      return
    }
    library.updateItemMutation.mutate(
      {
        itemId: item.item_id,
        payload: {
          metadata: {
            ...item.metadata,
            trashed: true,
            trashed_at: new Date().toISOString(),
          },
        },
      },
      {
        onSuccess: () =>
          setStatusMessage("Moved to Trash. The indexed source is preserved for recovery."),
      },
    )
  }

  function restoreFromTrash(documentId: string) {
    const item = resourceItemsByDocumentId.get(documentId)
    if (!item) return
    const metadata = { ...item.metadata }
    delete metadata.trashed
    delete metadata.trashed_at
    library.updateItemMutation.mutate(
      { itemId: item.item_id, payload: { metadata } },
      { onSuccess: () => setStatusMessage("Document restored to All Documents.") },
    )
  }

  function toggleSection(sectionId: string) {
    setCollapsedSections((current) => {
      const next = new Set(current)
      if (next.has(sectionId)) next.delete(sectionId)
      else next.add(sectionId)
      return next
    })
  }

  function usePdfSelection(next: PdfReaderSelection | null) {
    setSelection(
      next
        ? { source: "pdf", text: next.text, pageNumber: next.pageNumber }
        : null,
    )
  }

  function captureTextSelection() {
    window.setTimeout(() => {
      const current = window.getSelection()
      const article = articleRef.current
      if (!current || current.isCollapsed || current.rangeCount === 0 || !article) {
        setSelection(null)
        return
      }
      const range = current.getRangeAt(0)
      if (!article.contains(range.commonAncestorContainer)) return
      const text = current.toString().replace(/\s+/g, " ").trim()
      if (!text) return
      setSelection({
        source: "text",
        text,
        pageNumber: activeSection?.page_start ?? null,
      })
    }, 0)
  }

  function createSelectionCard(itemType: KnowledgeUserItemType) {
    if (!selection || !activeDocument) {
      setStatusMessage("Select a passage first.")
      return
    }
    const label =
      itemType === "note"
        ? "Note"
        : itemType === "concept"
          ? "Concept"
          : itemType === "highlight"
            ? "Highlight"
            : "Evidence"
    library.createItemMutation.mutate(
      {
        item_type: itemType,
        title: `${label} · ${activeSection?.heading || activeDocument.title}`,
        summary: selection.text,
        source_uri: activeDocument.source_uri,
        metadata: {
          document_id: activeDocument.document_id,
          section_id: activeSection?.section_id,
          section_heading: activeSection?.heading,
          page_start: activeSection?.page_start ?? null,
          page_end: activeSection?.page_end ?? null,
          selection_text: selection.text,
          selection_source: selection.source,
          pdf_page_number: selection.pageNumber ?? null,
        },
      },
      { onSuccess: () => setStatusMessage(`${label} saved to Knowledge.`) },
    )
  }

  function buildAcademicContext(text: string) {
    if (!activeDocument) return null
    return {
      context_id: `reading:${activeDocument.document_id}:${activeSection?.section_id || "selection"}`,
      document_id: activeDocument.document_id,
      text,
      resource_url: activeDocument.source_uri,
      resource_title: activeDocument.title,
      section_heading: activeSection?.heading || "",
      context_before: "",
      context_after: "",
      source_kind: "knowledge_document" as const,
    }
  }

  function explainWithAi() {
    if (!selection) {
      setStatusMessage("Select a passage first.")
      return
    }
    const context = buildAcademicContext(selection.text)
    if (!context) return
    workspace.useAcademicReadingContext(context)
    navigate("/agent", {
      state: {
        agentDraftPrompt: "Explain this selected passage in the context of the document.",
        autoSubmitAgentPrompt: true,
      },
    })
  }

  function translateSelection() {
    if (!selection) {
      setStatusMessage("Select a passage first.")
      return
    }
    const context = buildAcademicContext(selection.text)
    if (!context) return
    workspace.useAcademicReadingContext(context)
    navigate("/translation")
  }

  function copyText(value: string, message: string) {
    if (!value.trim()) return
    void navigator.clipboard
      .writeText(value)
      .then(() => setStatusMessage(message))
      .catch(() => setStatusMessage("Unable to copy to the clipboard."))
  }

  function addTag() {
    const tag = tagDraft.trim()
    if (!tag || !activeResourceItem || currentTags.includes(tag)) {
      setTagDraft("")
      return
    }
    library.updateItemMutation.mutate({
      itemId: activeResourceItem.item_id,
      payload: {
        metadata: {
          ...activeResourceItem.metadata,
          tags: [...currentTags, tag],
        },
      },
    })
    setTagDraft("")
  }

  function removeTag(tag: string) {
    if (!activeResourceItem) return
    library.updateItemMutation.mutate({
      itemId: activeResourceItem.item_id,
      payload: {
        metadata: {
          ...activeResourceItem.metadata,
          tags: currentTags.filter((candidate) => candidate !== tag),
        },
      },
    })
  }

  const filterCounts = documentFilterCounts(
    documents.filter((document) => !trashedDocumentIds.has(document.document_id)),
  )
  const activePage = selection?.pageNumber ?? activeSection?.page_start ?? 1
  const pageCount = controller.outlineQuery.data?.page_count ?? 0
  const hasActivePdf =
    activeDocument?.source_type.toLowerCase() === "pdf" && activeDocument.status === "ready"
  const previewUrl = activeDocument
    ? getKnowledgeDocumentPreviewUrl(activeDocument.document_id)
    : ""

  const documentsColumn = documentsCollapsed ? 48 : 290
  const outlineColumn = outlineCollapsed ? 48 : 250

  return (
    <section className="relative h-full min-h-0 overflow-hidden bg-white text-[#202124]">
      <div
        className="grid h-full min-h-0 min-w-[980px]"
        style={{
          gridTemplateColumns: `${documentsColumn}px ${outlineColumn}px minmax(360px, 1fr) 320px`,
        }}
      >
        <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-[#e6e6e6] bg-white">
          {documentsCollapsed ? (
            <CollapsedRail
              label="All Documents"
              icon={<FileText size={17} />}
              onExpand={() => setDocumentsCollapsed(false)}
            />
          ) : (
            <>
              <div className="shrink-0 px-4 pb-3 pt-4">
                <div className="flex items-center justify-between gap-2">
                  <h1 className="truncate text-[16px] font-semibold tracking-[-0.02em] text-[#171717]">
                    {showTrash ? "Trash" : "All Documents"}
                  </h1>
                  <button
                    type="button"
                    aria-label="Collapse All Documents"
                    title="Collapse All Documents"
                    onClick={() => setDocumentsCollapsed(true)}
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[7px] text-[#555] hover:bg-[#f0f0f0]"
                  >
                    <ChevronLeft size={15} />
                  </button>
                </div>

                <div className="mt-3 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={importDocument}
                    disabled={library.addMutation.isPending}
                    className="flex h-9 min-w-0 flex-1 items-center justify-center gap-2 rounded-[8px] border border-[#dfdfdf] bg-white px-3 text-[12px] font-medium text-[#252525] transition hover:bg-[#f5f5f5] disabled:opacity-40"
                  >
                    {library.addMutation.isPending ? (
                      <LoaderCircle size={15} className="animate-spin" />
                    ) : (
                      <Plus size={16} strokeWidth={1.8} />
                    )}
                    <span>Import Document</span>
                  </button>

                  <div className="relative">
                    <button
                      type="button"
                      aria-label="Sort documents"
                      title="Sort documents"
                      onClick={() => setSortOpen((value) => !value)}
                      className={`flex h-9 w-9 items-center justify-center rounded-[8px] border border-[#dfdfdf] transition ${
                        sortOpen ? "bg-[#ededed]" : "bg-white hover:bg-[#f5f5f5]"
                      }`}
                    >
                      <ArrowUpDown size={16} strokeWidth={1.7} />
                    </button>
                    {sortOpen && (
                      <div className="absolute right-0 top-11 z-40 w-44 overflow-hidden rounded-[9px] border border-[#dddddd] bg-white py-1.5 text-[11px] shadow-[0_12px_28px_rgba(0,0,0,.10)]">
                        <SortButton
                          label="Name"
                          active={sortMode === "name"}
                          onClick={() => {
                            setSortMode("name")
                            setSortOpen(false)
                          }}
                        />
                        <SortButton
                          label="Type"
                          active={sortMode === "type"}
                          onClick={() => {
                            setSortMode("type")
                            setSortOpen(false)
                          }}
                        />
                        <SortButton
                          label="Access date"
                          active={sortMode === "accessed"}
                          onClick={() => {
                            setSortMode("accessed")
                            setSortOpen(false)
                          }}
                        />
                        <SortButton
                          label="Manual order"
                          active={sortMode === "manual"}
                          onClick={() => {
                            setSortMode("manual")
                            setSortOpen(false)
                          }}
                        />
                      </div>
                    )}
                  </div>
                </div>

                {!showTrash && (
                  <div className="ait-scroll-panel mt-3 flex items-center gap-1.5 overflow-x-auto overscroll-x-contain pb-1">
                    <FilterChip
                      label="All"
                      count={filterCounts.all}
                      active={documentFilter === "all"}
                      onClick={() => setDocumentFilter("all")}
                    />
                    <FilterChip
                      label="PDF"
                      count={filterCounts.pdf}
                      active={documentFilter === "pdf"}
                      onClick={() => setDocumentFilter("pdf")}
                    />
                    <FilterChip
                      label="Word"
                      count={filterCounts.word}
                      active={documentFilter === "word"}
                      onClick={() => setDocumentFilter("word")}
                    />
                    <FilterChip
                      label="Markdown"
                      count={filterCounts.markdown}
                      active={documentFilter === "markdown"}
                      onClick={() => setDocumentFilter("markdown")}
                    />
                    <FilterChip
                      label="TXT"
                      count={filterCounts.text}
                      active={documentFilter === "text"}
                      onClick={() => setDocumentFilter("text")}
                    />
                    <FilterChip
                      label="Other"
                      count={filterCounts.other}
                      active={documentFilter === "other"}
                      onClick={() => setDocumentFilter("other")}
                    />
                  </div>
                )}

                <div className="relative mt-2.5">
                  <Search
                    size={14}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#8c8c8c]"
                  />
                  <input
                    value={documentSearch}
                    onChange={(event) => setDocumentSearch(event.target.value)}
                    placeholder="Search documents..."
                    className="h-9 w-full rounded-[8px] border border-[#e2e2e2] bg-white pl-8 pr-3 text-[11px] outline-none focus:border-[#bdbdbd]"
                  />
                </div>
              </div>

              <div
                className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-y-contain border-t border-[#eeeeee] px-2.5 py-2"
                style={{ scrollbarGutter: "stable" }}
              >
                {orderedDocuments.length ? (
                  orderedDocuments.map((document) => {
                    const active = document.document_id === controller.activeDocumentId
                    return (
                      <button
                        key={document.document_id}
                        type="button"
                        draggable={!showTrash}
                        onDragStart={(event) => {
                          setDraggedDocumentId(document.document_id)
                          event.dataTransfer.effectAllowed = "move"
                        }}
                        onDragOver={(event) => {
                          if (!showTrash) event.preventDefault()
                        }}
                        onDrop={(event) => {
                          event.preventDefault()
                          moveDocument(draggedDocumentId, document.document_id)
                          setDraggedDocumentId("")
                        }}
                        onDragEnd={() => setDraggedDocumentId("")}
                        onClick={() => selectDocument(document.document_id)}
                        className={`group flex w-full items-center gap-2 rounded-[8px] px-2 py-2.5 text-left transition ${
                          active ? "bg-[#eeeeee]" : "hover:bg-[#f6f6f6]"
                        } ${draggedDocumentId === document.document_id ? "opacity-50" : ""}`}
                      >
                        <span className="flex w-4 shrink-0 items-center justify-center text-[#8a8a8a]">
                          {!showTrash && <GripVertical size={13} strokeWidth={1.7} />}
                        </span>
                        <DocumentGlyph document={document} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[11.5px] font-semibold text-[#2d2d2d]">
                            {document.title || "Untitled document"}
                          </span>
                          <span className="mt-0.5 block truncate text-[10px] text-[#858585]">
                            {documentTypeLabel(document)} · {document.status}
                          </span>
                          <span className="mt-0.5 block truncate text-[9.5px] text-[#a0a0a0]">
                            {accessLabel(document, lastAccessed)}
                          </span>
                        </span>
                        <span className="flex shrink-0 items-center gap-0.5">
                          <span
                            className="flex h-7 w-7 items-center justify-center rounded-md text-[#777] opacity-0 transition group-hover:opacity-100"
                            aria-hidden="true"
                          >
                            <MoreHorizontal size={14} />
                          </span>
                          <span
                            role="button"
                            tabIndex={0}
                            aria-label={showTrash ? "Restore document" : "Move document to Trash"}
                            title={showTrash ? "Restore document" : "Move to Trash"}
                            onClick={(event) => {
                              event.stopPropagation()
                              if (showTrash) restoreFromTrash(document.document_id)
                              else moveToTrash(document.document_id)
                            }}
                            onKeyDown={(event) => {
                              if (event.key !== "Enter" && event.key !== " ") return
                              event.preventDefault()
                              event.stopPropagation()
                              if (showTrash) restoreFromTrash(document.document_id)
                              else moveToTrash(document.document_id)
                            }}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-[#555] opacity-70 transition hover:bg-[#e8e8e8] group-hover:opacity-100"
                          >
                            {showTrash ? <RotateCcw size={14} /> : <Trash2 size={14} />}
                          </span>
                        </span>
                      </button>
                    )
                  })
                ) : (
                  <div className="px-3 py-8 text-center text-[11px] leading-5 text-[#969696]">
                    {showTrash ? "Trash is empty." : "No documents match the current filter."}
                  </div>
                )}
              </div>

              <div className="shrink-0 border-t border-[#ececec] p-2.5">
                <button
                  type="button"
                  onClick={() => {
                    setShowTrash((value) => !value)
                    setDocumentFilter("all")
                    setDocumentSearch("")
                  }}
                  className={`flex w-full items-center gap-2 rounded-[8px] px-3 py-2 text-[11px] font-medium transition ${
                    showTrash
                      ? "bg-[#ededed] text-[#222]"
                      : "text-[#666] hover:bg-[#f5f5f5]"
                  }`}
                >
                  <Trash2 size={14} />
                  <span className="flex-1 text-left">Trash</span>
                  <span className="text-[10px] text-[#999]">{trashedDocumentIds.size}</span>
                </button>
              </div>
            </>
          )}
        </aside>

        <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-[#e6e6e6] bg-white">
          {outlineCollapsed ? (
            <CollapsedRail
              label="Outline"
              icon={<ListTree size={17} />}
              onExpand={() => setOutlineCollapsed(false)}
              footer={
                <button
                  type="button"
                  aria-label="Open Live Reading"
                  title="Live Reading"
                  onClick={() => setLiveReadingOpen(true)}
                  className="flex h-9 w-9 items-center justify-center rounded-[7px] text-[#444] hover:bg-[#eeeeee]"
                >
                  <Monitor size={17} />
                </button>
              }
            />
          ) : (
            <>
              <div className="shrink-0 px-3.5 pb-3 pt-4">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-[16px] font-semibold tracking-[-0.02em] text-[#171717]">
                    Outline
                  </h2>
                  <button
                    type="button"
                    aria-label="Collapse Outline"
                    title="Collapse Outline"
                    onClick={() => setOutlineCollapsed(true)}
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[7px] text-[#555] hover:bg-[#f0f0f0]"
                  >
                    <ChevronLeft size={15} />
                  </button>
                </div>
                <div className="relative mt-3">
                  <Search
                    size={14}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#8d8d8d]"
                  />
                  <input
                    value={outlineSearch}
                    onChange={(event) => setOutlineSearch(event.target.value)}
                    placeholder="Search outline..."
                    className="h-9 w-full rounded-[8px] border border-[#e2e2e2] bg-white pl-8 pr-3 text-[11px] outline-none focus:border-[#bdbdbd]"
                  />
                </div>
              </div>

              <div
                className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-y-contain border-t border-[#eeeeee] px-2.5 py-2"
                style={{ scrollbarGutter: "stable" }}
              >
                {!activeDocument ? (
                  <p className="px-3 py-5 text-[11px] leading-5 text-[#929292]">
                    Choose a document to inspect its structure.
                  </p>
                ) : activeDocument.status !== "ready" ? (
                  <p className="px-3 py-5 text-[11px] leading-5 text-[#929292]">
                    This document is still {activeDocument.status}. Outline becomes available after indexing.
                  </p>
                ) : controller.outlineQuery.isPending ? (
                  <div className="flex items-center gap-2 px-3 py-5 text-[11px] text-[#888]">
                    <LoaderCircle size={14} className="animate-spin" />
                    Parsing document structure…
                  </div>
                ) : outlineSections.length ? (
                  outlineSections.map((section) => {
                    const hasChildren = controller.sections.some(
                      (candidate) => candidate.parent_section_id === section.section_id,
                    )
                    const active = section.section_id === controller.activeSectionId
                    const collapsed = collapsedSections.has(section.section_id)
                    return (
                      <button
                        key={section.section_id}
                        type="button"
                        onClick={() => controller.selectSection(section.section_id)}
                        className={`flex w-full items-start gap-1.5 rounded-[7px] py-2 pr-2 text-left transition ${
                          active ? "bg-[#eeeeee]" : "hover:bg-[#f6f6f6]"
                        }`}
                        style={{
                          paddingLeft: `${8 + Math.min(Math.max(section.level - 1, 0), 5) * 12}px`,
                        }}
                      >
                        <span
                          role="button"
                          tabIndex={hasChildren ? 0 : -1}
                          aria-label={collapsed ? "Expand section" : "Collapse section"}
                          onClick={(event) => {
                            if (!hasChildren) return
                            event.stopPropagation()
                            toggleSection(section.section_id)
                          }}
                          onKeyDown={(event) => {
                            if (!hasChildren || (event.key !== "Enter" && event.key !== " ")) return
                            event.preventDefault()
                            event.stopPropagation()
                            toggleSection(section.section_id)
                          }}
                          className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-[#777]"
                        >
                          {hasChildren ? (
                            collapsed ? (
                              <ChevronRight size={12} />
                            ) : (
                              <ChevronDown size={12} />
                            )
                          ) : (
                            <span className="h-1 w-1 rounded-full bg-[#b5b5b5]" />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span
                            className={`block line-clamp-2 text-[11px] leading-4 ${
                              section.level <= 1
                                ? "font-semibold text-[#343434]"
                                : "text-[#606060]"
                            }`}
                          >
                            {section.heading || "Document introduction"}
                          </span>
                          {(section.has_equations || section.has_tables || section.has_figures) && (
                            <span className="mt-0.5 block text-[9px] text-[#9a9a9a]">
                              {[
                                section.has_equations ? "equations" : "",
                                section.has_tables ? "tables" : "",
                                section.has_figures ? "figures" : "",
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </span>
                          )}
                        </span>
                      </button>
                    )
                  })
                ) : (
                  <p className="px-3 py-5 text-[11px] leading-5 text-[#929292]">
                    No structured sections were detected.
                  </p>
                )}
              </div>

              <div className="shrink-0 border-t border-[#e8e8e8] p-3">
                <button
                  type="button"
                  onClick={() => setLiveReadingOpen(true)}
                  className="flex w-full items-center gap-3 rounded-[8px] border border-[#e1e1e1] bg-[#f7f7f7] px-3 py-3 text-left transition hover:bg-[#eeeeee]"
                >
                  <Monitor size={19} strokeWidth={1.65} className="shrink-0 text-[#333]" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[11.5px] font-semibold text-[#333]">
                      Live Reading
                    </span>
                    <span className="mt-0.5 block text-[9.5px] leading-4 text-[#777]">
                      Capture text from browser, Word, or desktop
                    </span>
                  </span>
                  <ChevronRight size={14} className="text-[#555]" />
                </button>
              </div>
            </>
          )}
        </aside>

        <main className="flex min-h-0 min-w-0 flex-col bg-[#fafafa]">
          <header className="flex h-[64px] shrink-0 items-center justify-between gap-4 border-b border-[#e6e6e6] bg-white px-4">
            <div className="min-w-0">
              <h2 className="truncate text-[17px] font-semibold tracking-[-0.025em] text-[#171717]">
                {activeDocument?.title || "Reading"}
              </h2>
              <p className="mt-0.5 truncate text-[10.5px] text-[#858585]">
                {activeDocument
                  ? `${documentTypeLabel(activeDocument)} · ${activeDocument.status}`
                  : "Import a document to begin"}
              </p>
            </div>
            {activeDocument && (
              <div className="flex shrink-0 items-center gap-2 text-[10px] text-[#666]">
                <span className="rounded-[7px] border border-[#dfdfdf] bg-white px-3 py-2">
                  {pageCount ? `${activePage} / ${pageCount}` : `Page ${activePage}`}
                </span>
                <button
                  type="button"
                  aria-label="Open source externally"
                  title="Open source externally"
                  onClick={() => void desktop.files.openEvidenceSource(activeDocument.source_uri)}
                  className="flex h-8 w-8 items-center justify-center rounded-[7px] text-[#444] hover:bg-[#f0f0f0]"
                >
                  <ExternalLink size={15} />
                </button>
              </div>
            )}
          </header>

          {!activeDocument ? (
            <EmptyReader onImport={importDocument} importing={library.addMutation.isPending} />
          ) : hasActivePdf ? (
            <PdfReaderSurface
              key={activeDocument.document_id}
              url={previewUrl}
              title={activeDocument.title}
              initialPage={Math.max(1, activePage)}
              onSelection={usePdfSelection}
            />
          ) : (
            <div className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-y-contain bg-[#fafafa] px-5 py-5">
              <div className="mx-auto min-h-full max-w-[820px] rounded-[8px] border border-[#e3e3e3] bg-white px-[7%] py-10 shadow-[0_1px_2px_rgba(0,0,0,.03)]">
                {controller.sectionQuery.isPending ? (
                  <div className="flex min-h-64 items-center justify-center gap-2 text-[12px] text-[#888]">
                    <LoaderCircle size={15} className="animate-spin" />
                    Loading section…
                  </div>
                ) : activeSection ? (
                  <>
                    <div className="border-b border-[#8a8a8a] pb-2 text-[10px] text-[#555]">
                      {activeDocument.title}
                    </div>
                    <h3 className="mt-8 font-serif text-[27px] font-medium leading-tight text-[#202020]">
                      {activeSection.heading || "Document introduction"}
                    </h3>
                    <article
                      ref={articleRef}
                      onMouseUp={captureTextSelection}
                      onKeyUp={captureTextSelection}
                      className="mt-6 whitespace-pre-wrap font-serif text-[16px] leading-[1.68] text-[#333]"
                    >
                      {activeSection.text || "This section contains no extractable text."}
                    </article>
                  </>
                ) : (
                  <div className="flex min-h-64 items-center justify-center text-[12px] text-[#888]">
                    Choose a ready document section from the Outline.
                  </div>
                )}
              </div>
            </div>
          )}
        </main>

        <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden border-l border-[#e6e6e6] bg-white">
          <div className="flex h-[64px] shrink-0 items-center justify-between border-b border-[#e8e8e8] px-4">
            <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#1f1f1f]">
              Evidence &amp; Actions
            </h2>
          </div>
          <div className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-4 pb-5">
            <PanelSection title="Source">
              {activeDocument ? (
                <div className="flex items-start gap-3">
                  <DocumentGlyph document={activeDocument} large />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11.5px] font-semibold text-[#333]">
                      {activeDocument.title}
                    </p>
                    <p className="mt-1 text-[10px] text-[#808080]">
                      {documentTypeLabel(activeDocument)} · {activeDocument.status}
                    </p>
                    <button
                      type="button"
                      onClick={() => navigate("/knowledge?view=library")}
                      className="mt-2 h-7 rounded-[7px] border border-[#e0e0e0] px-2.5 text-[10px] font-medium text-[#555] hover:bg-[#f5f5f5]"
                    >
                      View in Library
                    </button>
                  </div>
                </div>
              ) : (
                <p className="text-[11px] text-[#999]">No document selected.</p>
              )}
            </PanelSection>

            <PanelSection title="Section">
              <p className="text-[11.5px] font-semibold leading-4 text-[#3c3c3c]">
                {activeSection?.heading || "—"}
              </p>
              <p className="mt-1 text-[10px] text-[#8a8a8a]">
                {activeSection?.page_start ? `Page ${activeSection.page_start}` : "Page —"}
              </p>
            </PanelSection>

            <PanelSection
              title="Selected Passage"
              action={
                <CopyIcon
                  disabled={!selection}
                  onClick={() =>
                    copyText(selection?.text ?? "", "Selected passage copied.")
                  }
                />
              }
            >
              <div
                className={`rounded-[8px] px-3 py-3 text-[11px] leading-[1.5] ${
                  selection
                    ? "bg-[#f1f1f1] text-[#4b4b4b]"
                    : "bg-[#f7f7f7] text-[#999]"
                }`}
              >
                {selection?.text ||
                  "Select a passage in the document to capture evidence and actions."}
              </div>
            </PanelSection>

            <PanelSection title="Quick Actions">
              <div className="grid grid-cols-2 gap-2">
                <QuickAction
                  icon={<StickyNote size={14} />}
                  label="Add Note"
                  disabled={!selection}
                  onClick={() => createSelectionCard("note")}
                />
                <QuickAction
                  icon={<Sparkles size={14} />}
                  label="Explain with AI"
                  disabled={!selection}
                  onClick={explainWithAi}
                />
                <QuickAction
                  icon={<Link2 size={14} />}
                  label="Find Related"
                  disabled={!activeDocument}
                  onClick={() => navigate("/knowledge?view=graph")}
                />
                <QuickAction
                  icon={<Quote size={14} />}
                  label="Create Citation"
                  disabled={!activeDocument}
                  onClick={() => {
                    if (activeDocument) {
                      copyText(
                        `${activeDocument.title}. ${documentTypeLabel(activeDocument)}.`,
                        "Citation copied.",
                      )
                    }
                  }}
                />
                <QuickAction
                  icon={<Highlighter size={14} />}
                  label="Highlight"
                  disabled={!selection}
                  onClick={() => createSelectionCard("highlight")}
                />
                <QuickAction
                  icon={<Languages size={14} />}
                  label="Translate"
                  disabled={!selection}
                  onClick={translateSelection}
                />
                <QuickAction
                  icon={<Lightbulb size={14} />}
                  label="Save Concept"
                  disabled={!selection}
                  onClick={() => createSelectionCard("concept")}
                />
                <QuickAction
                  icon={<BookOpenCheck size={14} />}
                  label="Use Section"
                  disabled={!activeSection}
                  onClick={() => {
                    if (controller.attachSectionToAgent()) {
                      setStatusMessage("Current section attached to AI context.")
                    }
                  }}
                />
              </div>
            </PanelSection>

            <PanelSection title="Tags">
              {currentTags.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {currentTags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1 rounded-full bg-[#eeeeee] px-2 py-1 text-[9.5px] text-[#5d5d5d]"
                    >
                      {tag}
                      <button
                        type="button"
                        aria-label={`Remove ${tag}`}
                        onClick={() => removeTag(tag)}
                      >
                        <X size={9} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2">
                <div className="relative min-w-0 flex-1">
                  <Tag
                    size={12}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#999]"
                  />
                  <input
                    value={tagDraft}
                    onChange={(event) => setTagDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") addTag()
                    }}
                    disabled={!activeResourceItem}
                    placeholder="Add a tag..."
                    className="h-9 w-full rounded-[7px] border border-[#e1e1e1] bg-white pl-8 pr-3 text-[10.5px] outline-none focus:border-[#bdbdbd] disabled:bg-[#f7f7f7]"
                  />
                </div>
                <button
                  type="button"
                  aria-label="Add tag"
                  disabled={!activeResourceItem}
                  onClick={addTag}
                  className="flex h-9 w-9 items-center justify-center rounded-[7px] border border-[#e1e1e1] text-[#555] hover:bg-[#f5f5f5] disabled:opacity-35"
                >
                  <Plus size={14} />
                </button>
              </div>
            </PanelSection>
          </div>
        </aside>
      </div>

      {liveReadingOpen && (
        <LiveReadingDialog
          workspace={workspace}
          onClose={() => setLiveReadingOpen(false)}
        />
      )}

      {statusMessage && (
        <button
          type="button"
          onClick={() => setStatusMessage("")}
          className="absolute bottom-4 left-1/2 z-[70] -translate-x-1/2 rounded-full border border-[#d8d8d8] bg-white px-3.5 py-2 text-[10.5px] text-[#555] shadow-[0_8px_24px_rgba(0,0,0,.12)]"
        >
          {statusMessage}
        </button>
      )}
    </section>
  )
}

function CollapsedRail({
  label,
  icon,
  onExpand,
  footer,
}: {
  label: string
  icon: ReactNode
  onExpand: () => void
  footer?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-0 flex-col items-center bg-white py-3">
      <button
        type="button"
        aria-label={`Expand ${label}`}
        title={`Expand ${label}`}
        onClick={onExpand}
        className="flex h-9 w-9 items-center justify-center rounded-[7px] text-[#3f3f3f] hover:bg-[#eeeeee]"
      >
        <ChevronRight size={16} />
      </button>
      <div
        className="mt-3 flex h-9 w-9 items-center justify-center rounded-[7px] text-[#555]"
        title={label}
      >
        {icon}
      </div>
      <span
        className="mt-3 select-none text-[9px] font-medium tracking-[0.08em] text-[#777] [writing-mode:vertical-rl]"
        title={label}
      >
        {label}
      </span>
      {footer && <div className="mt-auto">{footer}</div>}
    </div>
  )
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-7 shrink-0 items-center gap-1 rounded-[7px] px-2.5 text-[10px] font-medium transition ${
        active
          ? "bg-[#e8e8e8] text-[#222]"
          : "bg-white text-[#666] hover:bg-[#f2f2f2]"
      }`}
    >
      <span>{label}</span>
      {count > 0 && <span className="text-[9px] text-[#999]">{count}</span>}
    </button>
  )
}

function SortButton({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full px-3 py-2 text-left ${
        active
          ? "bg-[#ededed] font-medium text-[#222]"
          : "text-[#5f5f5f] hover:bg-[#f6f6f6]"
      }`}
    >
      {label}
    </button>
  )
}

function DocumentGlyph({
  document,
  large = false,
}: {
  document: KnowledgeDocument
  large?: boolean
}) {
  return (
    <span
      className={`relative flex shrink-0 items-center justify-center rounded-[6px] border border-[#dcdcdc] bg-white text-[#333] ${
        large ? "h-11 w-11" : "h-8 w-8"
      }`}
    >
      <FileText size={large ? 18 : 16} strokeWidth={1.65} />
      <span
        className={`absolute bottom-0.5 font-semibold uppercase tracking-[-0.04em] ${
          large ? "text-[6px]" : "text-[5px]"
        }`}
      >
        {shortDocumentType(document)}
      </span>
    </span>
  )
}

function PanelSection({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="border-b border-[#e9e9e9] py-4 last:border-b-0">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h3 className="text-[11.5px] font-semibold text-[#363636]">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function CopyIcon({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Copy"
      disabled={disabled}
      onClick={onClick}
      className="flex h-7 w-7 items-center justify-center rounded-md text-[#666] hover:bg-[#f1f1f1] disabled:opacity-25"
    >
      <Copy size={13} />
    </button>
  )
}

function QuickAction({
  icon,
  label,
  disabled = false,
  onClick,
}: {
  icon: ReactNode
  label: string
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex h-9 items-center justify-center gap-2 rounded-[7px] border border-[#e1e1e1] bg-white px-2 text-[10px] font-medium text-[#4f4f4f] transition hover:bg-[#f5f5f5] disabled:cursor-default disabled:opacity-35"
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  )
}

function EmptyReader({
  onImport,
  importing,
}: {
  onImport: () => void
  importing: boolean
}) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-[#fafafa] p-8">
      <div className="max-w-sm text-center">
        <FileText size={28} className="mx-auto text-[#a5a5a5]" />
        <h3 className="mt-4 text-[14px] font-semibold text-[#333]">No document selected</h3>
        <p className="mt-2 text-[11px] leading-5 text-[#7d7d7d]">
          Import a PDF, Word, text, Markdown, or HTML document. Reading will index it and expose its structure in the Outline.
        </p>
        <button
          type="button"
          onClick={onImport}
          disabled={importing}
          className="mt-4 inline-flex h-9 items-center gap-2 rounded-[8px] border border-[#dddddd] bg-white px-4 text-[11px] font-medium hover:bg-[#f4f4f4] disabled:opacity-40"
        >
          {importing ? (
            <LoaderCircle size={14} className="animate-spin" />
          ) : (
            <Plus size={14} />
          )}
          Import Document
        </button>
      </div>
    </div>
  )
}

function LiveReadingDialog({
  workspace,
  onClose,
}: {
  workspace: TranslationWorkspaceController
  onClose: () => void
}) {
  const selection = workspace.readingSelection
  const browserPage = workspace.browserPage
  const title = selection?.resource_title || browserPage?.title || "Waiting for a live selection…"
  const section = selection?.section_heading || browserPage?.heading || ""

  return (
    <div
      className="absolute inset-0 z-[60] flex items-end justify-center bg-black/10 p-5"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-[760px] rounded-[14px] border border-[#d6d6d6] bg-white p-4 shadow-[0_18px_50px_rgba(0,0,0,.18)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Monitor size={17} />
              <h3 className="text-[13px] font-semibold text-[#252525]">Live Reading</h3>
            </div>
            <p className="mt-1 text-[10.5px] text-[#777]">
              Browser DOM, PDF UIA, Word, and desktop selection capture
            </p>
          </div>
          <button
            type="button"
            aria-label="Close Live Reading"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-[7px] text-[#555] hover:bg-[#f1f1f1]"
          >
            <X size={15} />
          </button>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="rounded-[9px] border border-[#e1e1e1] bg-[#f7f7f7] p-3">
            <p className="truncate text-[11px] font-semibold text-[#3a3a3a]">{title}</p>
            {section && (
              <p className="mt-1 truncate text-[9.5px] text-[#858585]">§ {section}</p>
            )}
            <p className="ait-scroll-panel mt-3 max-h-28 overflow-y-auto whitespace-pre-wrap text-[11px] leading-5 text-[#555]">
              {selection?.text ||
                "Select text in a supported browser, Word document, PDF reader, or desktop application. The captured passage will appear here."}
            </p>
          </div>
          <div className="space-y-2">
            <button
              type="button"
              onClick={() =>
                workspace.setFollowBrowserSelection(!workspace.followBrowserSelection)
              }
              className={`flex h-9 w-full items-center justify-between rounded-[8px] border border-[#dddddd] px-3 text-[10.5px] font-medium ${
                workspace.followBrowserSelection
                  ? "bg-[#eaeaea] text-[#222]"
                  : "bg-white text-[#666]"
              }`}
            >
              <span>Follow selection</span>
              <span>{workspace.followBrowserSelection ? "On" : "Off"}</span>
            </button>
            <button
              type="button"
              disabled={!selection}
              onClick={() => {
                workspace.useLatestSelection()
                onClose()
              }}
              className="flex h-9 w-full items-center justify-center rounded-[8px] border border-[#dddddd] bg-white px-3 text-[10.5px] font-medium text-[#444] hover:bg-[#f4f4f4] disabled:opacity-35"
            >
              Use latest selection
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function filterOutlineSections(
  sections: ReturnType<typeof useAcademicDocumentWorkspace>["sections"],
  query: string,
  collapsedSections: Set<string>,
) {
  const needle = query.trim().toLowerCase()
  if (needle) {
    return sections.filter((section) => section.heading.toLowerCase().includes(needle))
  }
  const byId = new Map(
    sections.map((section) => [section.section_id, section] as const),
  )
  return sections.filter((section) => {
    let parentId = section.parent_section_id
    while (parentId) {
      if (collapsedSections.has(parentId)) return false
      parentId = byId.get(parentId)?.parent_section_id ?? null
    }
    return true
  })
}

function orderDocuments(
  documents: KnowledgeDocument[],
  sortMode: SortMode,
  manualOrder: string[],
  lastAccessed: Record<string, string>,
) {
  if (sortMode === "name") {
    return [...documents].sort((a, b) => a.title.localeCompare(b.title))
  }
  if (sortMode === "type") {
    return [...documents].sort(
      (a, b) =>
        documentTypeLabel(a).localeCompare(documentTypeLabel(b)) ||
        a.title.localeCompare(b.title),
    )
  }
  if (sortMode === "accessed") {
    return [...documents].sort(
      (a, b) => accessTimestamp(b, lastAccessed) - accessTimestamp(a, lastAccessed),
    )
  }
  const rank = new Map(manualOrder.map((id, index) => [id, index] as const))
  return [...documents].sort((a, b) => {
    const aRank = rank.get(a.document_id) ?? Number.MAX_SAFE_INTEGER
    const bRank = rank.get(b.document_id) ?? Number.MAX_SAFE_INTEGER
    if (aRank !== bRank) return aRank - bRank
    return accessTimestamp(b, lastAccessed) - accessTimestamp(a, lastAccessed)
  })
}

function documentFilterCounts(documents: KnowledgeDocument[]) {
  const result = {
    all: documents.length,
    pdf: 0,
    word: 0,
    markdown: 0,
    text: 0,
    other: 0,
  }
  for (const document of documents) {
    if (matchesDocumentFilter(document, "pdf")) result.pdf += 1
    else if (matchesDocumentFilter(document, "word")) result.word += 1
    else if (matchesDocumentFilter(document, "markdown")) result.markdown += 1
    else if (matchesDocumentFilter(document, "text")) result.text += 1
    else result.other += 1
  }
  return result
}

function matchesDocumentFilter(
  document: KnowledgeDocument,
  filter: DocumentFilter,
): boolean {
  if (filter === "all") return true
  const type = document.source_type.toLowerCase()
  if (filter === "pdf") return type === "pdf"
  if (filter === "word") return type === "doc" || type === "docx"
  if (filter === "markdown") return type === "md" || type === "markdown"
  if (filter === "text") return type === "txt"
  return ![
    "pdf",
    "doc",
    "docx",
    "md",
    "markdown",
    "txt",
  ].includes(type)
}

function shortDocumentType(document: KnowledgeDocument): string {
  const type = document.source_type.toLowerCase()
  if (type === "docx" || type === "doc") return "W"
  if (type === "markdown" || type === "md") return "MD"
  return type.slice(0, 3) || "DOC"
}

function documentTypeLabel(document: KnowledgeDocument): string {
  const type = document.source_type.toLowerCase()
  if (type === "pdf") return "PDF"
  if (type === "doc" || type === "docx") return "Word"
  if (type === "txt") return "TXT"
  if (type === "md" || type === "markdown") return "Markdown"
  if (type === "html" || type === "htm") return "HTML"
  return type ? type.toUpperCase() : "Document"
}

function accessTimestamp(
  document: KnowledgeDocument,
  lastAccessed: Record<string, string>,
): number {
  const value = lastAccessed[document.document_id] || document.indexed_at || ""
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : 0
}

function accessLabel(
  document: KnowledgeDocument,
  lastAccessed: Record<string, string>,
): string {
  const value = lastAccessed[document.document_id]
  if (value) {
    const date = new Date(value)
    if (!Number.isNaN(date.getTime())) return `Last opened ${date.toLocaleDateString()}`
  }
  if (document.indexed_at) {
    const date = new Date(document.indexed_at)
    if (!Number.isNaN(date.getTime())) return `Added ${date.toLocaleDateString()}`
  }
  return "Not opened yet"
}

function readStringArray(key: string): string[] {
  if (typeof window === "undefined") return []
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "[]")
    return Array.isArray(value)
      ? value.filter((candidate): candidate is string => typeof candidate === "string")
      : []
  } catch {
    return []
  }
}

function readStringRecord(key: string): Record<string, string> {
  if (typeof window === "undefined") return {}
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "{}")
    if (!value || typeof value !== "object" || Array.isArray(value)) return {}
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    )
  } catch {
    return {}
  }
}

function writeJson(key: string, value: unknown) {
  if (typeof window === "undefined") return
  window.localStorage.setItem(key, JSON.stringify(value))
}
