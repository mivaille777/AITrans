import { BookOpenText, ChevronDown, FileText, LibraryBig } from "lucide-react"
import { useMemo } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { Button } from "../../shared/ui/Button"
import { ResearchWorkflowActions } from "../agent/components/ResearchWorkflowActions"
import KnowledgePaperReaderPanel from "../knowledge/KnowledgePaperReaderPanel"
import type { KnowledgeDocument } from "../knowledge/knowledge-types"
import type { KnowledgeLibraryController } from "../knowledge/useKnowledgeLibrary"
import { useKnowledgeLibrary } from "../knowledge/useKnowledgeLibrary"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import BrowserReadingContextPanel from "./BrowserReadingContextPanel"
import {
  buildCloseReadingPaperParams,
  buildOpenReadingPaperParams,
  resolveReadingPaperId,
} from "./reading-navigation"

export default function ReadingWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const library = useKnowledgeLibrary()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const paperItemId = resolveReadingPaperId(searchParams)
  const selection = workspace.readingSelection
  const browserPage = workspace.browserPage
  const isBrowserSelection = selection?.source_kind === "browser"
  const title = selection?.resource_title || (isBrowserSelection ? browserPage?.title : "") || "—"
  const section = selection?.section_heading || (isBrowserSelection ? browserPage?.heading : "") || "—"
  const locator = selection?.resource_url || selection?.local_locator || (isBrowserSelection ? browserPage?.url : "") || "—"
  const hasNearbyContext = Boolean(selection?.context_before || selection?.context_after)

  if (paperItemId) {
    return (
      <KnowledgePaperReaderPanel
        paperItemId={paperItemId}
        library={library}
        workspace={workspace}
        onBack={() => setSearchParams(buildCloseReadingPaperParams(searchParams), { replace: true })}
      />
    )
  }

  return (
    <div className="space-y-4">
      <ReadingLibraryLanding
        library={library}
        onOpenPaper={(itemId) => setSearchParams(buildOpenReadingPaperParams(searchParams, itemId))}
        onManageLibrary={() => navigate("/knowledge?view=library")}
      />

      <BrowserReadingContextPanel
        browserStatus={workspace.browserStatus}
        readingSelection={selection}
        browserPage={browserPage}
        followBrowserSelection={workspace.followBrowserSelection}
        autoTranslateSelection={workspace.autoTranslateSelection}
        autoTranslating={workspace.autoTranslating}
        onFollowBrowserSelectionChange={workspace.setFollowBrowserSelection}
        onAutoTranslateSelectionChange={workspace.setAutoTranslateSelection}
      />

      <details className="group overflow-hidden rounded-[16px] border border-slate-200/70 bg-white">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 text-xs font-medium text-slate-600 hover:bg-slate-50/70">
          <span className="flex items-center gap-2">
            <BookOpenText size={14} className="text-slate-400" />
            Live browser / desktop reading context
            {selection && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-semibold uppercase text-emerald-700">{selection.source_kind || "reading"}</span>}
          </span>
          <ChevronDown size={14} className="text-slate-400 transition group-open:rotate-180" />
        </summary>

        <div className="border-t border-slate-100 p-4">
          {selection ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,.6fr)]">
              <div>
                <p className="whitespace-pre-wrap rounded-[14px] border border-slate-200/70 bg-slate-50/55 p-4 text-sm leading-7 text-slate-700">{selection.text}</p>
                {hasNearbyContext && (
                  <div className="mt-3 grid gap-3 lg:grid-cols-2">
                    <ContextBlock label="Before" value={selection.context_before} />
                    <ContextBlock label="After" value={selection.context_after} />
                  </div>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <MetadataRow label="Title" value={title} span />
                <MetadataRow label="Section" value={section} span />
                <MetadataRow label="Source" value={selection.source_kind || "—"} />
                <MetadataRow label="Application" value={selection.application || "—"} />
                <MetadataRow label="Page" value={selection.page_number ? String(selection.page_number) : "—"} />
                <MetadataRow label="Provider" value={selection.provider || "—"} />
                <MetadataRow label="Locator" value={locator} mono span />
              </dl>
            </div>
          ) : (
            <p className="text-xs leading-5 text-slate-500">
              Select text in a browser, PDF, Word document, or another supported desktop app. Live selections complement the canonical indexed-paper reader above without creating a second document-reader workflow.
            </p>
          )}
        </div>
      </details>
    </div>
  )
}

function ReadingLibraryLanding({
  library,
  onOpenPaper,
  onManageLibrary,
}: {
  library: KnowledgeLibraryController
  onOpenPaper: (itemId: string) => void
  onManageLibrary: () => void
}) {
  const items = library.itemsQuery.data?.items ?? []
  const documents = library.documentsQuery.data?.documents ?? []
  const documentsById = useMemo(
    () => new Map(documents.map((document) => [document.document_id, document] as const)),
    [documents],
  )
  const papers = items.filter((item) => item.item_type === "paper")
  const loading = library.itemsQuery.isPending || library.documentsQuery.isPending
  const loadError = library.itemsQuery.error ?? library.documentsQuery.error

  return (
    <section className="ait-surface overflow-hidden">
      <header className="flex flex-col gap-4 border-b border-slate-200/70 px-6 py-5 lg:flex-row lg:items-center lg:justify-between lg:px-7">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Reading workspace</p>
          <h1 className="mt-2 text-lg font-semibold tracking-tight text-slate-950">Read indexed papers with AI-aware context</h1>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            Reading is the canonical document-reading surface. Open an indexed paper here for structured outline navigation, Text/PDF modes, Evidence, Highlight, Note, Concept, Translate, and Ask AI actions. Knowledge remains the place to organize and manage those artifacts.
          </p>
          <div className="mt-4 max-w-2xl border-t border-slate-100 pt-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Start from the current paper</p>
            <ResearchWorkflowActions available={["quick_read", "analyze_visuals"]} compact variant="inline" />
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onManageLibrary}><LibraryBig size={14} />Manage Knowledge Library</Button>
      </header>

      {loadError ? (
        <div role="alert" className="m-5 rounded-[14px] border border-rose-100 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700 lg:mx-7">
          Unable to load indexed papers: {errorMessage(loadError)}
        </div>
      ) : null}

      <div className="p-5 lg:p-7">
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
            <div className="ait-skeleton h-36 rounded-[18px]" />
            <div className="ait-skeleton h-36 rounded-[18px]" />
            <div className="ait-skeleton h-36 rounded-[18px]" />
          </div>
        ) : papers.length === 0 ? (
          <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50/45 p-7 text-center">
            <LibraryBig size={24} className="mx-auto text-slate-300" />
            <p className="mt-3 text-sm font-semibold text-slate-700">No paper cards are ready to read.</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">Import and manage documents in Knowledge Library, then return here to read them.</p>
            <Button className="mt-4" size="sm" onClick={onManageLibrary}>Open Knowledge Library</Button>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {papers.map((paper) => {
              const document = paper.resource_document_id ? documentsById.get(paper.resource_document_id) : undefined
              return (
                <PaperLaunchCard
                  key={paper.item_id}
                  title={paper.title}
                  summary={paper.summary}
                  document={document}
                  onOpen={() => onOpenPaper(paper.item_id)}
                />
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}

function PaperLaunchCard({
  title,
  summary,
  document,
  onOpen,
}: {
  title: string
  summary: string
  document?: KnowledgeDocument
  onOpen: () => void
}) {
  const hasIndexedSource = Boolean(document)
  return (
    <article className="flex min-h-36 flex-col rounded-[18px] border border-slate-200/70 bg-white p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="rounded-[11px] bg-slate-100 p-2 text-slate-500"><FileText size={16} /></div>
        <div className="min-w-0 flex-1">
          <h2 className="line-clamp-2 text-sm font-semibold leading-5 text-slate-850">{title || "Untitled paper"}</h2>
          <p className="mt-1 text-[10px] uppercase tracking-[0.08em] text-slate-400">
            {document ? `${document.source_type} · ${document.status} · ${document.chunk_count} chunks` : "Paper card · no indexed source"}
          </p>
        </div>
      </div>
      <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">{summary || "No summary saved."}</p>
      <div className="mt-auto pt-4">
        <Button size="xs" disabled={!hasIndexedSource} onClick={onOpen}><BookOpenText size={13} />{hasIndexedSource ? "Read paper" : "Attach source in Knowledge"}</Button>
      </div>
    </article>
  )
}

function ContextBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[13px] border border-slate-200/60 bg-white p-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</p>
      <p className="mt-2 line-clamp-5 text-xs leading-5 text-slate-600">{value || "No nearby context captured."}</p>
    </div>
  )
}

function MetadataRow({
  label,
  value,
  mono = false,
  span = false,
}: {
  label: string
  value: string
  mono?: boolean
  span?: boolean
}) {
  return (
    <div className={`rounded-[12px] border border-slate-200/60 bg-slate-50/45 px-3 py-2.5 ${span ? "col-span-2" : ""}`}>
      <dt className="text-[9px] font-medium uppercase tracking-[0.12em] text-slate-400">{label}</dt>
      <dd className={`mt-1 break-words text-slate-700 ${mono ? "font-mono text-[10px]" : "text-xs"}`}>{value}</dd>
    </div>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to reach the Knowledge API."
}
