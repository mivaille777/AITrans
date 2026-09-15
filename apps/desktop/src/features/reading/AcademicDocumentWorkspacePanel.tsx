import {
  BookOpenCheck,
  FilePlus2,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Sigma,
  Table2,
} from "lucide-react"

import type { KnowledgeDocumentOutlineSection } from "../knowledge/knowledge-types"
import { academicPageLabel } from "./academic-workspace-state"
import type { AcademicDocumentWorkspaceController } from "./useAcademicDocumentWorkspace"

export default function AcademicDocumentWorkspacePanel({
  controller,
}: {
  controller: AcademicDocumentWorkspaceController
}) {
  const {
    library,
    documents,
    activeDocument,
    outlineQuery,
    sections,
    activeSectionId,
    sectionQuery,
    selectDocument,
    selectSection,
    attachSectionToAgent,
    attachedContext,
  } = controller

  const attached = Boolean(
    attachedContext &&
      activeDocument &&
      attachedContext.document_id === activeDocument.document_id &&
      attachedContext.context_id.endsWith(`:${activeSectionId}`),
  )

  return (
    <section className="ait-surface overflow-hidden">
      <div className="border-b border-slate-200/70 px-6 py-5 lg:px-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Academic document workspace
            </p>
            <h2 className="mt-2 text-lg font-semibold tracking-tight text-slate-950">
              Read indexed papers by document structure
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
              Choose an indexed document, inspect its section hierarchy, then attach one bounded section as the Agent&apos;s frozen reading context.
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => library.addMutation.mutate()}
            disabled={library.addMutation.isPending}
          >
            {library.addMutation.isPending ? (
              <LoaderCircle size={15} className="animate-spin" />
            ) : (
              <FilePlus2 size={15} />
            )}
            Import document
          </button>
        </div>
      </div>

      <div className="grid min-h-[420px] xl:h-[clamp(480px,58vh,660px)] xl:min-h-0 xl:grid-cols-[260px_minmax(240px,0.75fr)_minmax(0,1.25fr)] xl:grid-rows-[minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-b border-slate-200/70 bg-slate-50/45 p-4 xl:border-b-0 xl:border-r">
          <p className="shrink-0 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Documents · {documents.length}
          </p>
          <div className="ait-scroll-panel mt-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto overscroll-contain pr-1">
            {documents.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-200 bg-white/60 p-3 text-xs leading-5 text-slate-500">
                Import a PDF, Word, text, Markdown, or HTML document to start an academic workspace.
              </p>
            ) : (
              documents.map((document) => (
                <button
                  key={document.document_id}
                  type="button"
                  onClick={() => selectDocument(document.document_id)}
                  className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                    activeDocument?.document_id === document.document_id
                      ? "border-slate-300 bg-white shadow-sm"
                      : "border-transparent hover:border-slate-200 hover:bg-white/70"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <FileText size={16} className="mt-0.5 shrink-0 text-slate-400" />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-slate-800">
                        {document.title || "Untitled document"}
                      </p>
                      <p className="mt-1 text-[10px] uppercase tracking-[0.08em] text-slate-400">
                        {document.source_type} · {document.status} · {document.chunk_count} chunks
                      </p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </aside>

        <aside className="flex min-h-0 flex-col border-b border-slate-200/70 p-4 xl:border-b-0 xl:border-r">
          <div className="flex shrink-0 items-center justify-between gap-3 px-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              Outline
            </p>
            {outlineQuery.data && (
              <span className="text-[10px] text-slate-400">
                {outlineQuery.data.page_count || "—"} pages · {outlineQuery.data.section_count} sections
              </span>
            )}
          </div>
          <div className="ait-scroll-panel mt-3 max-h-[420px] min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-1 xl:max-h-none">
            {!activeDocument ? (
              <p className="px-2 text-xs leading-5 text-slate-500">Choose a document first.</p>
            ) : activeDocument.status !== "ready" ? (
              <p className="px-2 text-xs leading-5 text-slate-500">
                This document is still {activeDocument.status}. The academic outline becomes available after indexing is ready.
              </p>
            ) : outlineQuery.isPending ? (
              <p className="flex items-center gap-2 px-2 text-xs text-slate-500">
                <LoaderCircle size={14} className="animate-spin" /> Parsing document structure…
              </p>
            ) : outlineQuery.isError ? (
              <p className="px-2 text-xs leading-5 text-rose-600">Unable to load the document outline.</p>
            ) : sections.length === 0 ? (
              <p className="px-2 text-xs leading-5 text-slate-500">No structured sections were detected.</p>
            ) : (
              sections.map((section) => (
                <OutlineButton
                  key={section.section_id}
                  section={section}
                  active={section.section_id === activeSectionId}
                  onClick={() => selectSection(section.section_id)}
                />
              ))
            )}
          </div>
        </aside>

        <div className="flex min-h-0 flex-col p-5 lg:p-6">
          {activeDocument && sectionQuery.data ? (
            <>
              <div className="flex shrink-0 flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Section preview
                  </p>
                  <h3 className="mt-2 text-base font-semibold text-slate-900">
                    {sectionQuery.data.heading || "Document introduction"}
                  </h3>
                  <p className="mt-1 text-xs text-slate-400">
                    {academicPageLabel(sectionQuery.data.page_start, sectionQuery.data.page_end)}
                    {sectionQuery.data.truncated ? " · preview truncated" : ""}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => attachSectionToAgent()}
                  className={`inline-flex items-center gap-2 rounded-xl border px-3.5 py-2 text-xs font-semibold transition ${
                    attached
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <BookOpenCheck size={15} />
                  {attached ? "Attached to Agent" : "Use in Agent"}
                </button>
              </div>

              <div className="ait-scroll-panel mt-4 max-h-[420px] min-h-0 flex-1 overflow-y-auto overscroll-contain rounded-[18px] border border-slate-200/70 bg-slate-50/65 p-4.5 xl:max-h-none">
                <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
                  {sectionQuery.data.text || "This section contains no extractable text."}
                </p>
              </div>
              <p className="mt-3 shrink-0 text-[11px] leading-5 text-slate-400">
                Agent context is bounded separately from this preview. Very long sections attach only a safe leading window and are marked as incomplete context.
              </p>
            </>
          ) : sectionQuery.isPending && activeDocument?.status === "ready" ? (
            <div className="flex min-h-48 flex-1 items-center justify-center gap-2 text-sm text-slate-500">
              <LoaderCircle size={16} className="animate-spin" /> Loading section preview…
            </div>
          ) : (
            <div className="flex min-h-48 flex-1 items-center justify-center rounded-[18px] border border-dashed border-slate-200 bg-slate-50/45 p-6 text-center">
              <div>
                <FileText size={24} className="mx-auto text-slate-300" />
                <p className="mt-3 text-sm font-medium text-slate-700">Choose a ready document section.</p>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  The workspace reuses the same structure-aware parser that feeds RAG indexing.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function OutlineButton({
  section,
  active,
  onClick,
}: {
  section: KnowledgeDocumentOutlineSection
  active: boolean
  onClick: () => void
}) {
  const indent = Math.min(Math.max(section.level - 1, 0), 4) * 12
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg border px-2.5 py-2 text-left transition ${
        active
          ? "border-slate-300 bg-slate-50"
          : "border-transparent hover:border-slate-200 hover:bg-slate-50/70"
      }`}
      style={{ paddingLeft: `${10 + indent}px` }}
    >
      <div className="flex items-start justify-between gap-2">
        <span className={`line-clamp-2 text-xs ${section.reference_section ? "text-slate-400" : "text-slate-700"}`}>
          {section.heading || "Document introduction"}
        </span>
        <span className="flex shrink-0 items-center gap-1 text-slate-300">
          {section.has_equations && <Sigma size={11} />}
          {section.has_tables && <Table2 size={11} />}
          {section.has_figures && <ImageIcon size={11} />}
        </span>
      </div>
      <p className="mt-1 text-[10px] text-slate-400">
        {academicPageLabel(section.page_start, section.page_end)} · {section.block_count} blocks
      </p>
    </button>
  )
}
