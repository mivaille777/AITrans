import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  BookOpenText,
  Bot,
  FileText,
  MessageSquareText,
  NotebookPen,
} from "lucide-react"

import { getResearchSource } from "../../api/research"
import { queryKeys } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { EmptyState } from "../../shared/ui/EmptyState"

export default function ResearchSourceProfilePanel({
  sourceId,
  selectedSectionHeading,
  onSelectSection,
}: {
  sourceId: string
  selectedSectionHeading: string
  onSelectSection: (heading: string) => void
}) {
  const sourceQuery = useQuery({
    queryKey: queryKeys.research.source(sourceId),
    queryFn: () => getResearchSource(sourceId),
    enabled: Boolean(sourceId),
    staleTime: 2_000,
  })

  if (sourceQuery.isPending) {
    return <div className="p-6 text-sm text-slate-400">Loading source profile…</div>
  }

  if (sourceQuery.isError || !sourceQuery.data) {
    return (
      <div className="ait-scroll-panel h-full overflow-y-auto p-6">
        <EmptyState
          icon={<BookOpenText size={28} strokeWidth={1.5} />}
          title="Unable to load source profile"
          description={sourceQuery.error instanceof Error ? sourceQuery.error.message : "The selected research source is unavailable."}
        />
      </div>
    )
  }

  const source = sourceQuery.data

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-slate-100 px-5 py-5 lg:px-6">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Source profile
        </p>
        <div className="mt-2 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold tracking-tight text-slate-900">{source.display_title}</h3>
            <p className="mt-2 max-w-2xl text-xs leading-5 text-slate-500">
              Evidence captured from this source is grouped by a normalized source identity rather than by individual selections.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Badge tone="info">{formatFamily(source.source_family)}</Badge>
            <Badge>{formatQuality(source.identity_quality)}</Badge>
          </div>
        </div>
        {source.resource_locator && (
          <p className="mt-4 break-all rounded-xl bg-slate-50 px-3 py-2 font-mono text-[10px] leading-4 text-slate-400">
            {source.resource_locator}
          </p>
        )}
      </header>

      <div className="ait-scroll-panel min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 lg:px-6">
        <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-5">
          <Metric icon={<FileText size={15} />} label="Evidence" value={source.note_count} />
          <Metric icon={<BookOpenText size={15} />} label="Sections" value={source.section_count} />
          <Metric icon={<NotebookPen size={15} />} label="Annotations" value={source.annotation_count} />
          <Metric icon={<Bot size={15} />} label="AI evidence" value={source.ai_evidence_count} />
          <Metric icon={<MessageSquareText size={15} />} label="Linked chats" value={source.linked_conversation_count} />
        </div>

        <section className="mt-5 rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-slate-800">Sections represented in saved evidence</p>
              <p className="mt-1 text-[10px] leading-4 text-slate-500">
                Section grouping comes only from captured Reading Context headings; it is not a synthetic full-document outline.
              </p>
            </div>
            {selectedSectionHeading && (
              <Button size="xs" variant="ghost" onClick={() => onSelectSection("")}>
                Clear section filter
              </Button>
            )}
          </div>

          <div className="mt-3 space-y-2">
            {source.sections.map((section) => {
              const active = selectedSectionHeading === section.heading
              return (
                <button
                  key={section.section_id}
                  type="button"
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    active
                      ? "border-cyan-300 bg-cyan-50"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                  onClick={() => onSelectSection(active ? "" : section.heading)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-xs font-semibold leading-5 text-slate-800">{section.heading}</p>
                    <span className="shrink-0 text-[10px] text-slate-400">{section.note_count} evidence</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
                    <span>{section.annotation_count} annotations</span>
                    <span>{section.ai_evidence_count} AI</span>
                    <span>{section.linked_conversation_count} chats</span>
                  </div>
                </button>
              )
            })}
          </div>
        </section>

        <section className="mt-4 rounded-2xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-800">Identity provenance</p>
          <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
            <IdentityRow label="Provider source kind" value={source.source_kind || "unknown"} />
            <IdentityRow label="Normalized family" value={source.source_family} />
            <IdentityRow label="Identity quality" value={source.identity_quality} />
            <IdentityRow label="Latest evidence update" value={formatTimestamp(source.updated_at)} />
          </dl>
          {source.identity_quality !== "locator" && (
            <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-[10px] leading-4 text-amber-800">
              This source currently lacks a stable URL or file locator, so grouping relies on captured title metadata. Native PDF/Word providers can improve this quality once they expose document locators.
            </p>
          )}
        </section>
      </div>
    </div>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-2 text-slate-400">
        {icon}
        <span className="text-[10px] font-medium uppercase tracking-[0.12em]">{label}</span>
      </div>
      <p className="mt-2 text-lg font-semibold text-slate-900">{value}</p>
    </div>
  )
}

function IdentityRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.12em] text-slate-400">{label}</dt>
      <dd className="mt-1 break-words font-medium text-slate-700">{value}</dd>
    </div>
  )
}

function formatFamily(value: string): string {
  const labels: Record<string, string> = {
    browser: "Web",
    pdf: "PDF",
    word: "Word",
    desktop: "Desktop",
    other: "Other",
  }
  return labels[value] ?? value
}

function formatQuality(value: string): string {
  if (value === "locator") return "Stable locator"
  if (value === "title") return "Title identity"
  return "Note-local identity"
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
