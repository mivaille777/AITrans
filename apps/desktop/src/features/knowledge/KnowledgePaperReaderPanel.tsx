import {
  Archive,
  Bookmark,
  BookOpenText,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  Highlighter,
  Languages,
  LibraryBig,
  Lightbulb,
  Link2,
  LoaderCircle,
  Maximize2,
  MoreHorizontal,
  Plus,
  Quote,
  Search,
  Sparkles,
  StickyNote,
  Tag,
  Trash2,
  X,
} from "lucide-react"
import { useMemo, useRef, useState, type ReactNode } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { desktop } from "../../desktop"
import PdfReaderSurface, { type PdfReaderSelection } from "../reading/PdfReaderSurface"
import { buildOpenReadingPaperParams } from "../reading/reading-navigation"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { paperPageLabel, type PaperReaderSelectionSource } from "./paper-reader-state"
import type { KnowledgeDocument, KnowledgeItem } from "./knowledge-types"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"
import { usePaperReader } from "./usePaperReader"

type ReaderMode = "text" | "pdf"
type SourceFilter = "all" | "arxiv" | "web" | "bookmarks"

interface ReaderSelectionState {
  source: PaperReaderSelectionSource
  text: string
  left: number
  top: number
  pageNumber?: number | null
}

interface KnowledgePaperReaderPanelProps {
  paperItemId: string
  library: KnowledgeLibraryController
  workspace: TranslationWorkspaceController
  onBack: () => void
}

export default function KnowledgePaperReaderPanel(props: KnowledgePaperReaderPanelProps) {
  return <KnowledgePaperReaderContent key={props.paperItemId} {...props} />
}

function KnowledgePaperReaderContent({
  paperItemId,
  library,
  workspace,
  onBack,
}: KnowledgePaperReaderPanelProps) {
  const reader = usePaperReader(paperItemId, library, workspace)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const articleRef = useRef<HTMLDivElement | null>(null)
  const [selection, setSelection] = useState<ReaderSelectionState | null>(null)
  const [readerMode, setReaderMode] = useState<ReaderMode>("text")
  const [zoom, setZoom] = useState(1.25)
  const [searchOpen, setSearchOpen] = useState(false)
  const [documentSearch, setDocumentSearch] = useState("")
  const [leftSearch, setLeftSearch] = useState("")
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all")
  const [moreOpen, setMoreOpen] = useState(false)
  const [contextWide, setContextWide] = useState(false)
  const [tagDraft, setTagDraft] = useState("")
  const [bookmarkOverride, setBookmarkOverride] = useState<boolean | null>(null)
  const [statusMessage, setStatusMessage] = useState("")
  const [openError, setOpenError] = useState("")

  const { paper, document, sectionQuery } = reader
  const items = library.itemsQuery.data?.items ?? []
  const documents = library.documentsQuery.data?.documents ?? []
  const documentsById = useMemo(
    () => new Map(documents.map((candidate) => [candidate.document_id, candidate] as const)),
    [documents],
  )

  const papers = useMemo(
    () => items
      .filter((item) => item.item_type === "paper" && Boolean(item.resource_document_id))
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)),
    [items],
  )
  const filteredRecentPapers = useMemo(() => {
    const needle = leftSearch.trim().toLowerCase()
    return papers.filter((candidate) => {
      const source = candidate.source_uri.toLowerCase()
      const bookmarked = Boolean(candidate.metadata.bookmarked)
      const filterMatches = sourceFilter === "all"
        || sourceFilter === "arxiv" && source.includes("arxiv")
        || sourceFilter === "web" && /^https?:/i.test(candidate.source_uri) && !source.includes("arxiv")
        || sourceFilter === "bookmarks" && bookmarked
      const searchMatches = !needle
        || candidate.title.toLowerCase().includes(needle)
        || candidate.summary.toLowerCase().includes(needle)
      return filterMatches && searchMatches
    }).slice(0, 7)
  }, [leftSearch, papers, sourceFilter])

  const arxivCount = papers.filter((candidate) => candidate.source_uri.toLowerCase().includes("arxiv")).length
  const webCount = papers.filter((candidate) => /^https?:/i.test(candidate.source_uri) && !candidate.source_uri.toLowerCase().includes("arxiv")).length
  const bookmarkCount = papers.filter((candidate) => Boolean(candidate.metadata.bookmarked)).length
  const noteCount = items.filter((candidate) => candidate.item_type === "note").length

  function captureSelection() {
    window.setTimeout(() => {
      const current = window.getSelection()
      if (!current || current.isCollapsed || current.rangeCount === 0) {
        setSelection(null)
        return
      }
      const range = current.getRangeAt(0)
      const article = articleRef.current
      if (!article || !article.contains(range.commonAncestorContainer)) {
        return
      }
      const text = current.toString().replace(/\s+/g, " ").trim()
      if (!text) {
        setSelection(null)
        return
      }
      const rect = range.getBoundingClientRect()
      setSelection({
        source: "text",
        text,
        left: rect.left + rect.width / 2,
        top: rect.top,
        pageNumber: sectionQuery.data?.page_start ?? null,
      })
    }, 0)
  }

  function usePdfSelection(pdfSelection: PdfReaderSelection | null) {
    setSelection(pdfSelection)
  }

  function openPaper(itemId: string) {
    setSelection(null)
    setSearchParams(buildOpenReadingPaperParams(searchParams, itemId))
  }

  function selectSiblingSection(direction: -1 | 1) {
    const index = reader.sections.findIndex((section) => section.section_id === reader.activeSectionId)
    if (index < 0) return
    const target = reader.sections[index + direction]
    if (!target) return
    setSelection(null)
    reader.selectSection(target.section_id)
  }

  function selectionTarget(current: ReaderSelectionState) {
    return {
      source: current.source,
      text: current.text,
      pageNumber: current.pageNumber,
    }
  }

  function createSelectionCard(itemType: "highlight" | "note" | "concept" | "evidence") {
    if (!selection) {
      setStatusMessage("Select a passage first.")
      return
    }
    reader.createDerivedMutation.mutate(
      { itemType, ...selectionTarget(selection) },
      {
        onSuccess: () => {
          setStatusMessage(itemType === "note" ? "Note added." : `${capitalize(itemType)} saved.`)
          window.getSelection()?.removeAllRanges()
          setSelection(null)
        },
      },
    )
  }

  function explainWithAi() {
    if (!selection || !paper) {
      setStatusMessage("Select a passage first.")
      return
    }
    const target = selectionTarget(selection)
    reader.createDerivedMutation.mutate(
      { itemType: "evidence", ...target },
      {
        onSuccess: (evidence) => {
          void reader.attachSelectionToAgent(target).then((attached) => {
            if (!attached) return
            navigate("/agent", {
              state: {
                agentDraftPrompt: "Explain this evidence in the context of the paper.",
                autoSubmitAgentPrompt: true,
                knowledgeAgentContext: {
                  item: evidence,
                  writeback: {
                    itemType: "insight",
                    operation: "research",
                    relationType: "derived_from",
                  },
                  sourceText: target.text,
                  documentIds: document ? [document.document_id] : [],
                },
              },
            })
          })
        },
      },
    )
  }

  function translateSelection() {
    if (!selection) {
      setStatusMessage("Select a passage first.")
      return
    }
    reader.translationMutation.mutate(selection.text, {
      onSuccess: () => setStatusMessage("Translation is ready in the translation workspace."),
    })
  }

  function copyText(value: string, successMessage: string) {
    if (!value.trim()) return
    void navigator.clipboard.writeText(value).then(() => setStatusMessage(successMessage))
  }

  if (!paper || paper.item_type !== "paper") {
    return <ReaderMessage title="Paper unavailable" description="The requested knowledge card no longer exists or is not a paper." onBack={onBack} />
  }

  if (!document) {
    return <ReaderMessage title="No indexed source attached" description="This paper card does not have a local indexed document yet." onBack={onBack} />
  }

  const activePaper = paper
  const activeDocument = document
  const canPreviewPdf = activeDocument.source_type === "pdf" && Boolean(reader.previewUrl)
  const pageCount = reader.outlineQuery.data?.page_count ?? 0
  const activePage = selection?.pageNumber
    ?? reader.activeOutlineSection?.page_start
    ?? sectionQuery.data?.page_start
    ?? 1
  const activeIndex = reader.sections.findIndex((section) => section.section_id === reader.activeSectionId)
  const currentTags = Array.isArray(activePaper.metadata.tags) ? activePaper.metadata.tags : []
  const bookmarked = bookmarkOverride ?? Boolean(activePaper.metadata.bookmarked)
  const currentPassage = selection?.text ?? "Select a passage in the document to capture evidence and context."
  const currentSection = sectionQuery.data?.heading || reader.activeOutlineSection?.heading || "Document section"
  const currentPageLabel = pageCount ? `${Math.max(1, activePage)} / ${pageCount}` : String(Math.max(1, activePage))
  const gridClass = contextWide
    ? "grid-cols-[280px_minmax(520px,1fr)_430px]"
    : "grid-cols-[280px_minmax(520px,1fr)_360px]"

  function toggleBookmark() {
    const next = !bookmarked
    setBookmarkOverride(next)
    library.updateItemMutation.mutate({
      itemId: activePaper.item_id,
      payload: { metadata: { ...activePaper.metadata, bookmarked: next } },
    })
  }

  function addTag() {
    const normalized = tagDraft.trim()
    if (!normalized || currentTags.includes(normalized)) {
      setTagDraft("")
      return
    }
    library.updateItemMutation.mutate({
      itemId: activePaper.item_id,
      payload: { metadata: { ...activePaper.metadata, tags: [...currentTags, normalized] } },
    })
    setTagDraft("")
  }

  function removeTag(tag: string) {
    library.updateItemMutation.mutate({
      itemId: activePaper.item_id,
      payload: { metadata: { ...activePaper.metadata, tags: currentTags.filter((candidate) => candidate !== tag) } },
    })
  }

  function openSourceExternally() {
    setOpenError("")
    void desktop.files.openEvidenceSource(activeDocument.source_uri).catch((error: unknown) => {
      setOpenError(error instanceof Error ? error.message : "Unable to open source.")
    })
  }

  return (
    <section className="relative h-full min-h-0 overflow-hidden bg-white text-[#202124]">
      <div className={`grid h-full min-h-0 min-w-[1120px] ${gridClass}`}>
        <aside className="flex min-h-0 flex-col border-r border-[#e6e6e6] bg-white">
          <div className="flex items-center justify-between px-[18px] pb-3 pt-[18px]">
            <h2 className="text-[16px] font-semibold tracking-[-0.02em] text-[#161616]">Recent Documents</h2>
            <button
              type="button"
              aria-label="Add document"
              className="flex h-9 w-9 items-center justify-center rounded-[9px] border border-[#e4e4e4] bg-white text-[#242424] transition hover:bg-[#f6f6f6] disabled:opacity-40"
              onClick={() => library.addMutation.mutate()}
              disabled={library.addMutation.isPending}
            >
              {library.addMutation.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={19} strokeWidth={1.8} />}
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-4">
            <div className="space-y-1">
              {filteredRecentPapers.map((candidate) => {
                const active = candidate.item_id === activePaper.item_id
                const candidateDocument = candidate.resource_document_id ? documentsById.get(candidate.resource_document_id) : undefined
                return (
                  <button
                    key={candidate.item_id}
                    type="button"
                    onClick={() => openPaper(candidate.item_id)}
                    className={`flex w-full items-start gap-3 rounded-[8px] px-3 py-3 text-left transition ${active ? "bg-[#f1f1f1]" : "hover:bg-[#f7f7f7]"}`}
                  >
                    <FileText size={19} strokeWidth={1.65} className="mt-0.5 shrink-0 text-[#303030]" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-[#242424]">{candidate.title || "Untitled paper"}</span>
                      <span className="mt-1 block truncate text-[12px] text-[#737373]">{paperSubtitle(candidate, candidateDocument)}</span>
                    </span>
                  </button>
                )
              })}
              {!filteredRecentPapers.length && (
                <p className="px-3 py-5 text-[12px] leading-5 text-[#8a8a8a]">No papers match this source or search.</p>
              )}
            </div>

            <div className="mx-2 my-5 h-px bg-[#e9e9e9]" />

            <div className="mb-2 flex items-center justify-between px-2">
              <h3 className="text-[15px] font-semibold text-[#1f1f1f]">All Sources</h3>
              <button
                type="button"
                aria-label="Search documents"
                className="flex h-8 w-8 items-center justify-center rounded-md text-[#3e3e3e] hover:bg-[#f4f4f4]"
                onClick={() => setLeftSearch((value) => value ? "" : " ")}
              >
                <Search size={17} strokeWidth={1.7} />
              </button>
            </div>

            <div className="px-2 pb-2">
              <div className="relative">
                <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8a8a8a]" />
                <input
                  value={leftSearch}
                  onChange={(event) => setLeftSearch(event.target.value)}
                  placeholder="Search papers"
                  className="h-9 w-full rounded-[8px] border border-[#e5e5e5] bg-white pl-8 pr-3 text-[12px] outline-none transition focus:border-[#c9c9c9]"
                />
              </div>
            </div>

            <SourceButton icon={<Archive size={18} />} label="arXiv" count={`${arxivCount} papers`} active={sourceFilter === "arxiv"} onClick={() => setSourceFilter(sourceFilter === "arxiv" ? "all" : "arxiv")} />
            <SourceButton icon={<Link2 size={18} />} label="Web Papers" count={`${webCount} papers`} active={sourceFilter === "web"} onClick={() => setSourceFilter(sourceFilter === "web" ? "all" : "web")} />
            <SourceButton icon={<LibraryBig size={18} />} label="My Papers" count={`${papers.length} papers`} active={sourceFilter === "all"} onClick={() => setSourceFilter("all")} />
            <SourceButton icon={<Bookmark size={18} />} label="Bookmarks" count={`${bookmarkCount} items`} active={sourceFilter === "bookmarks"} onClick={() => setSourceFilter(sourceFilter === "bookmarks" ? "all" : "bookmarks")} />
            <SourceButton icon={<StickyNote size={18} />} label="Reading Notes" count={`${noteCount} items`} />
            <SourceButton icon={<Trash2 size={18} />} label="Trash" count="0 items" />
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-col bg-[#fafafa]">
          <header className="relative flex h-[68px] shrink-0 items-center justify-between gap-4 border-b border-[#e6e6e6] bg-white px-5">
            <div className="min-w-0">
              <h1 className="truncate text-[19px] font-semibold leading-6 tracking-[-0.025em] text-[#151515]">{activePaper.title}</h1>
              <p className="mt-0.5 truncate text-[11.5px] text-[#777]">{paperByline(activePaper, activeDocument)}</p>
            </div>

            <div className="flex shrink-0 items-center gap-1.5">
              {searchOpen && (
                <div className="mr-1 flex h-9 items-center gap-2 rounded-[8px] border border-[#e1e1e1] bg-white px-2.5">
                  <Search size={14} className="text-[#777]" />
                  <input
                    autoFocus
                    value={documentSearch}
                    onChange={(event) => setDocumentSearch(event.target.value)}
                    placeholder="Find in section"
                    className="w-32 bg-transparent text-[12px] outline-none"
                  />
                  {documentSearch && <span className="text-[10px] text-[#999]">{countMatches(sectionQuery.data?.text ?? "", documentSearch)}</span>}
                </div>
              )}
              <ToolbarIcon label="Previous section" disabled={activeIndex <= 0} onClick={() => selectSiblingSection(-1)}><ChevronLeft size={18} /></ToolbarIcon>
              <div className="flex h-9 min-w-[74px] items-center justify-center rounded-[8px] border border-[#e4e4e4] bg-white px-3 text-[12px] font-medium text-[#555]">{currentPageLabel}</div>
              <ToolbarIcon label="Next section" disabled={activeIndex < 0 || activeIndex >= reader.sections.length - 1} onClick={() => selectSiblingSection(1)}><ChevronRight size={18} /></ToolbarIcon>
              <label className="ml-1 flex h-9 items-center rounded-[8px] border border-[#e4e4e4] bg-white px-2.5 text-[12px] text-[#555]">
                <select
                  aria-label="Zoom"
                  value={String(zoom)}
                  onChange={(event) => setZoom(Number(event.target.value))}
                  className="cursor-pointer appearance-none bg-transparent pr-3 font-medium outline-none"
                  disabled={readerMode === "pdf"}
                >
                  <option value="1">100%</option>
                  <option value="1.1">110%</option>
                  <option value="1.25">125%</option>
                  <option value="1.4">140%</option>
                  <option value="1.5">150%</option>
                </select>
                <ChevronDown size={13} />
              </label>
              <ToolbarIcon label="Search" active={searchOpen} onClick={() => setSearchOpen((value) => !value)}><Search size={18} /></ToolbarIcon>
              <ToolbarIcon label="Bookmark" active={bookmarked} onClick={toggleBookmark}><Bookmark size={18} fill={bookmarked ? "currentColor" : "none"} /></ToolbarIcon>
              <div className="relative">
                <ToolbarIcon label="More" active={moreOpen} onClick={() => setMoreOpen((value) => !value)}><MoreHorizontal size={19} /></ToolbarIcon>
                {moreOpen && (
                  <div className="absolute right-0 top-11 z-40 w-44 overflow-hidden rounded-[10px] border border-[#dedede] bg-white py-1.5 text-[12px] shadow-[0_12px_30px_rgba(0,0,0,.12)]">
                    <MenuButton active={readerMode === "text"} onClick={() => { setReaderMode("text"); setMoreOpen(false) }}>Reader view</MenuButton>
                    <MenuButton disabled={!canPreviewPdf} active={readerMode === "pdf"} onClick={() => { if (canPreviewPdf) setReaderMode("pdf"); setMoreOpen(false) }}>PDF view</MenuButton>
                    <MenuButton onClick={openSourceExternally}>Open source externally</MenuButton>
                  </div>
                )}
              </div>
            </div>
          </header>

          {openError && <div className="shrink-0 border-b border-[#f1cccc] bg-[#fff4f4] px-5 py-2 text-[11px] text-[#a34545]">{openError}</div>}

          {readerMode === "pdf" && canPreviewPdf ? (
            <div className="min-h-0 flex-1">
              <PdfReaderSurface
                url={reader.previewUrl}
                title={activePaper.title}
                initialPage={Math.max(1, activePage)}
                onSelection={usePdfSelection}
              />
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto bg-[#fafafa] px-4 py-3.5">
              {sectionQuery.isPending ? (
                <div className="flex h-full items-center justify-center gap-2 text-[13px] text-[#777]"><LoaderCircle size={16} className="animate-spin" />Loading section…</div>
              ) : sectionQuery.data ? (
                <div className="mx-auto min-h-[calc(100%-12px)] max-w-[880px] rounded-[7px] border border-[#e3e3e3] bg-white px-[7.2%] pb-8 pt-10 shadow-[0_1px_2px_rgba(0,0,0,.025)]">
                  <div className="flex items-center justify-between border-b border-[#777] pb-2 font-serif text-[11px] text-[#343434]">
                    <span className="truncate pr-4">{activePaper.title}</span>
                    <span className="shrink-0">{compactSourceLabel(activePaper.source_uri, activeDocument.source_type)}</span>
                  </div>

                  <div className="pt-9">
                    <h2 className="font-serif text-[29px] font-medium leading-tight tracking-[-0.025em] text-[#171717]">{currentSection}</h2>
                    {sectionQuery.data.truncated && <span className="mt-2 inline-block rounded bg-[#f4f1e8] px-2 py-1 text-[10px] text-[#7b6b3f]">Preview truncated</span>}
                    <article
                      ref={articleRef}
                      onMouseUp={captureSelection}
                      onKeyUp={captureSelection}
                      className="mt-6 select-text whitespace-pre-wrap font-serif text-[#2d2d2d]"
                      style={{ fontSize: `${15.5 * zoom}px`, lineHeight: 1.62 }}
                    >
                      <HighlightedText text={sectionQuery.data.text || "This section contains no extractable text."} query={documentSearch} />
                    </article>
                  </div>

                  <div className="mt-9 border-t border-[#777] pt-2 text-center font-serif text-[11px] text-[#444]">{Math.max(1, activePage)}</div>
                </div>
              ) : (
                <div className="flex h-full items-center justify-center text-[13px] text-[#777]">Choose a ready section from the document.</div>
              )}
            </div>
          )}
        </main>

        <aside className="flex min-h-0 flex-col border-l border-[#e6e6e6] bg-white">
          <div className="flex h-[66px] shrink-0 items-center justify-between border-b border-[#e9e9e9] px-5">
            <h2 className="text-[16px] font-semibold tracking-[-0.02em] text-[#1a1a1a]">Evidence &amp; Context</h2>
            <button
              type="button"
              aria-label="Expand context panel"
              className="flex h-8 w-8 items-center justify-center rounded-md text-[#444] transition hover:bg-[#f3f3f3]"
              onClick={() => setContextWide((value) => !value)}
            >
              <Maximize2 size={17} strokeWidth={1.7} />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5">
            <ContextSection title="Source">
              <div className="flex items-start gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[9px] border border-[#e4e4e4] bg-[#fafafa]">
                  <FileText size={20} strokeWidth={1.55} />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-[13px] font-semibold text-[#242424]">{activePaper.title}</h3>
                  <p className="mt-1 truncate text-[12px] text-[#777]">{paperSubtitle(activePaper, activeDocument)}</p>
                  <p className="mt-1 truncate text-[11px] text-[#8a8a8a]">{compactSourceLabel(activePaper.source_uri, activeDocument.source_type)}</p>
                  <div className="mt-2.5 flex items-center gap-2">
                    <button type="button" className="h-8 rounded-[7px] border border-[#e2e2e2] px-3 text-[11px] font-medium text-[#444] hover:bg-[#f7f7f7]" onClick={() => navigate("/knowledge?view=library")}>View in Library</button>
                    <button type="button" aria-label="Open source externally" className="flex h-8 w-8 items-center justify-center rounded-[7px] border border-[#e2e2e2] text-[#444] hover:bg-[#f7f7f7]" onClick={openSourceExternally}><ExternalLink size={15} /></button>
                  </div>
                </div>
              </div>
            </ContextSection>

            <ContextSection title="Section">
              <p className="text-[13px] font-semibold text-[#343434]">{currentSection}</p>
              <p className="mt-1 text-[11px] text-[#868686]">{paperPageLabel(sectionQuery.data?.page_start ?? null, sectionQuery.data?.page_end ?? null)}</p>
            </ContextSection>

            <ContextSection
              title="Selected Passage"
              action={<CopyButton disabled={!selection} onClick={() => copyText(selection?.text ?? "", "Selected passage copied.")} />}
            >
              <div className={`rounded-[8px] px-3.5 py-3 text-[12px] leading-[1.48] ${selection ? "bg-[#f2f2f2] text-[#474747]" : "bg-[#f7f7f7] text-[#999]"}`}>
                {currentPassage}
              </div>
            </ContextSection>

            <ContextSection title="Quick Actions">
              <div className="grid grid-cols-2 gap-2">
                <QuickAction icon={<StickyNote size={15} />} label="Add Note" disabled={!selection} onClick={() => createSelectionCard("note")} />
                <QuickAction icon={<Sparkles size={15} />} label="Explain with AI" disabled={!selection} onClick={explainWithAi} />
                <QuickAction icon={<Link2 size={15} />} label="Find Related" onClick={() => navigate("/knowledge?view=graph")} />
                <QuickAction icon={<Quote size={15} />} label="Create Citation" onClick={() => copyText(buildCitation(activePaper, activeDocument), "Citation copied.")} />
                <QuickAction icon={<Highlighter size={15} />} label="Highlight" disabled={!selection} onClick={() => createSelectionCard("highlight")} />
                <QuickAction icon={<Languages size={15} />} label="Translate" disabled={!selection} onClick={translateSelection} />
                <QuickAction icon={<Lightbulb size={15} />} label="Save Concept" disabled={!selection} onClick={() => createSelectionCard("concept")} />
                <QuickAction icon={<BookOpenText size={15} />} label="Use Section" onClick={() => {
                  if (reader.attachSectionToAgent()) setStatusMessage("Current section attached to AI context.")
                }} />
              </div>
            </ContextSection>

            <ContextSection title="Tags">
              {currentTags.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {currentTags.map((tag) => (
                    <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-[#f1f1f1] px-2.5 py-1 text-[10px] text-[#555]">
                      {tag}
                      <button type="button" aria-label={`Remove ${tag}`} onClick={() => removeTag(tag)}><X size={10} /></button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2">
                <div className="relative min-w-0 flex-1">
                  <Tag size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#999]" />
                  <input
                    value={tagDraft}
                    onChange={(event) => setTagDraft(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") addTag() }}
                    placeholder="Add a tag..."
                    className="h-9 w-full rounded-[7px] border border-[#e2e2e2] bg-white pl-8 pr-3 text-[11px] outline-none transition focus:border-[#c8c8c8]"
                  />
                </div>
                <button type="button" aria-label="Add tag" onClick={addTag} className="flex h-9 w-9 items-center justify-center rounded-[7px] border border-[#e2e2e2] text-[#555] hover:bg-[#f7f7f7]"><Plus size={15} /></button>
              </div>
            </ContextSection>
          </div>
        </aside>
      </div>

      {statusMessage && (
        <button
          type="button"
          onClick={() => setStatusMessage("")}
          className="absolute bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-full border border-[#dedede] bg-white px-3 py-1.5 text-[11px] text-[#555] shadow-lg"
        >
          {statusMessage}
        </button>
      )}
    </section>
  )
}

function SourceButton({
  icon,
  label,
  count,
  active = false,
  onClick,
}: {
  icon: ReactNode
  label: string
  count: string
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-[8px] px-3 py-2.5 text-left transition ${active ? "bg-[#f3f3f3]" : "hover:bg-[#f7f7f7]"}`}
    >
      <span className="flex w-5 shrink-0 items-center justify-center text-[#3d3d3d]">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[12.5px] font-medium text-[#363636]">{label}</span>
        <span className="mt-0.5 block text-[10.5px] text-[#8a8a8a]">{count}</span>
      </span>
    </button>
  )
}

function ToolbarIcon({
  label,
  children,
  disabled = false,
  active = false,
  onClick,
}: {
  label: string
  children: ReactNode
  disabled?: boolean
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`flex h-9 w-9 items-center justify-center rounded-[7px] transition ${active ? "bg-[#ededed] text-[#111]" : "text-[#333] hover:bg-[#f2f2f2]"} disabled:cursor-default disabled:opacity-25`}
    >
      {children}
    </button>
  )
}

function MenuButton({ children, active = false, disabled = false, onClick }: {
  children: ReactNode
  active?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`block w-full px-3 py-2 text-left transition ${active ? "bg-[#f2f2f2] font-medium text-[#222]" : "text-[#555] hover:bg-[#f6f6f6]"} disabled:opacity-40`}
    >
      {children}
    </button>
  )
}

function ContextSection({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-[#e9e9e9] py-4 last:border-b-0">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-[13px] font-semibold text-[#2d2d2d]">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function CopyButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Copy"
      disabled={disabled}
      onClick={onClick}
      className="flex h-7 w-7 items-center justify-center rounded-md text-[#666] hover:bg-[#f2f2f2] disabled:opacity-25"
    >
      <Copy size={14} />
    </button>
  )
}

function QuickAction({ icon, label, disabled = false, onClick }: {
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
      className="flex h-9 items-center justify-center gap-2 rounded-[7px] border border-[#e1e1e1] bg-white px-2 text-[10.5px] font-medium text-[#4a4a4a] transition hover:bg-[#f7f7f7] disabled:cursor-default disabled:opacity-40"
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  )
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim()
  if (!needle) return <>{text}</>
  const lower = text.toLowerCase()
  const target = needle.toLowerCase()
  const parts: ReactNode[] = []
  let cursor = 0
  let index = lower.indexOf(target)
  let key = 0
  while (index >= 0) {
    if (index > cursor) parts.push(text.slice(cursor, index))
    parts.push(<mark key={key++} className="rounded-[2px] bg-[#dde4e8] px-0.5 text-inherit">{text.slice(index, index + needle.length)}</mark>)
    cursor = index + needle.length
    index = lower.indexOf(target, cursor)
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

function ReaderMessage({ title, description, onBack }: { title: string; description: string; onBack: () => void }) {
  return (
    <section className="flex h-full min-h-[520px] items-center justify-center bg-[#fafafa] p-8">
      <div className="max-w-md rounded-[12px] border border-[#e4e4e4] bg-white p-7 text-center shadow-sm">
        <FileText size={26} className="mx-auto text-[#999]" />
        <h2 className="mt-4 text-[16px] font-semibold text-[#222]">{title}</h2>
        <p className="mt-2 text-[12px] leading-5 text-[#777]">{description}</p>
        <button type="button" onClick={onBack} className="mt-5 rounded-[8px] border border-[#dedede] px-4 py-2 text-[12px] font-medium text-[#444] hover:bg-[#f6f6f6]">Back to Reading</button>
      </div>
    </section>
  )
}

function paperSubtitle(paper: KnowledgeItem, document?: KnowledgeDocument) {
  const authors = normalizeAuthors(paper.metadata.authors)
  const year = normalizeYear(paper.metadata.year)
  if (authors || year) return [authors, year].filter(Boolean).join(" · ")
  if (document) return `${document.source_type.toUpperCase()} · ${document.status}`
  return compactSourceLabel(paper.source_uri, "paper")
}

function paperByline(paper: KnowledgeItem, document: KnowledgeDocument) {
  const authors = normalizeAuthors(paper.metadata.authors)
  const year = normalizeYear(paper.metadata.year)
  const source = compactSourceLabel(paper.source_uri, document.source_type)
  return [authors, year, source].filter(Boolean).join("  |  ") || `${document.source_type.toUpperCase()} indexed document`
}

function normalizeAuthors(value: unknown): string {
  if (typeof value === "string") return value.trim()
  if (Array.isArray(value)) return value.filter((candidate): candidate is string => typeof candidate === "string").join(", ")
  return ""
}

function normalizeYear(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(Math.round(value))
  if (typeof value === "string") return value.trim()
  return ""
}

function compactSourceLabel(sourceUri: string, fallback: string): string {
  const source = sourceUri.trim()
  if (!source) return fallback.toUpperCase()
  const lower = source.toLowerCase()
  if (lower.includes("arxiv")) {
    const match = source.match(/(?:abs|pdf)\/(\d{4}\.\d{4,5})/i)
    return match ? `arXiv:${match[1]}` : "arXiv"
  }
  if (lower.includes("aclanthology")) return "ACL Anthology"
  if (/^https?:/i.test(source)) {
    try {
      return new URL(source).hostname.replace(/^www\./, "")
    } catch {
      return "Web source"
    }
  }
  return fallback.toUpperCase()
}

function buildCitation(paper: KnowledgeItem, document: KnowledgeDocument): string {
  const authors = normalizeAuthors(paper.metadata.authors)
  const year = normalizeYear(paper.metadata.year)
  const lead = authors ? `${authors}${year ? ` (${year})` : ""}. ` : year ? `(${year}). ` : ""
  return `${lead}${paper.title}. ${compactSourceLabel(paper.source_uri, document.source_type)}.`
}

function countMatches(text: string, query: string): number {
  const needle = query.trim().toLowerCase()
  if (!needle) return 0
  const haystack = text.toLowerCase()
  let count = 0
  let cursor = 0
  while (cursor < haystack.length) {
    const index = haystack.indexOf(needle, cursor)
    if (index < 0) break
    count += 1
    cursor = index + needle.length
  }
  return count
}

function capitalize(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value
}