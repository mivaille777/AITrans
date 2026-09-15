import { BookOpenText, ChevronDown } from "lucide-react"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import AcademicDocumentWorkspacePanel from "./AcademicDocumentWorkspacePanel"
import BrowserReadingContextPanel from "./BrowserReadingContextPanel"
import { useAcademicDocumentWorkspace } from "./useAcademicDocumentWorkspace"

export default function ReadingWorkspace({
  workspace,
}: {
  workspace: TranslationWorkspaceController
}) {
  const academicWorkspace = useAcademicDocumentWorkspace(workspace)
  const selection = workspace.readingSelection
  const browserPage = workspace.browserPage
  const isBrowserSelection = selection?.source_kind === "browser"
  const title = selection?.resource_title || (isBrowserSelection ? browserPage?.title : "") || "—"
  const section = selection?.section_heading || (isBrowserSelection ? browserPage?.heading : "") || "—"
  const locator = selection?.resource_url || selection?.local_locator || (isBrowserSelection ? browserPage?.url : "") || "—"
  const hasNearbyContext = Boolean(selection?.context_before || selection?.context_after)

  return (
    <div className="space-y-4">
      <AcademicDocumentWorkspacePanel controller={academicWorkspace} />

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
            External browser / desktop reading selection
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
              Select text in a browser, PDF, Word document, or another supported desktop app. External selections share the same reading contract but stay secondary to the indexed-document workspace.
            </p>
          )}
        </div>
      </details>
    </div>
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
