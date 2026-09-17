import { BookOpenCheck, ChevronDown, FileText, LoaderCircle, NotebookText, ServerOff } from "lucide-react"
import type { ReactNode } from "react"

import { EmptyState } from "../../shared/ui/EmptyState"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { ResearchWorkflowActions } from "../agent/components/ResearchWorkflowActions"
import EvidenceReviewPanel from "./EvidenceReviewPanel"
import KnowledgeResearchBridgePanel from "./KnowledgeResearchBridgePanel"
import ResearchProjectPanel from "./ResearchProjectPanel"
import ResearchScopePanel from "./ResearchScopePanel"
import ResearchWorkspace from "./ResearchWorkspace"
import WritingDraftPanel from "./WritingDraftPanel"

type BackendState = "checking" | "connected" | "offline"

export default function ResearchRoute({
  backendState,
  workspace,
}: {
  backendState: BackendState
  workspace: TranslationWorkspaceController
}) {
  if (backendState === "checking") {
    return (
      <section className="mx-auto max-w-[1220px] rounded-[18px] border border-slate-200/70 bg-white p-6 shadow-[0_8px_28px_rgba(15,23,42,0.04)]">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <LoaderCircle size={17} className="animate-spin text-slate-400" />
          Connecting Research Workspace…
        </div>
        <div className="mt-6 grid gap-3 lg:grid-cols-[220px_280px_minmax(0,1fr)]">
          <SkeletonBlock className="h-72" />
          <SkeletonBlock className="h-72" />
          <SkeletonBlock className="h-72" />
        </div>
      </section>
    )
  }

  if (backendState === "offline") {
    return (
      <EmptyState
        className="mx-auto max-w-[1220px] rounded-[18px] border border-slate-200/70 bg-white py-16 shadow-[0_8px_28px_rgba(15,23,42,0.04)]"
        icon={<ServerOff size={24} strokeWidth={1.6} />}
        title="Research Workspace is waiting for the backend"
        description="Your research data remains local. Start or reconnect the AITranslator backend and this workspace will resume automatically."
      />
    )
  }

  return (
    <div className="mx-auto max-w-[1220px] space-y-4">
      <section className="ait-surface overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-200/70 px-5 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-6">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Research control center</p>
            <h1 className="mt-1 text-lg font-semibold tracking-tight text-slate-950">Choose evidence, then decide the next research step</h1>
            <p className="mt-1 text-xs leading-5 text-slate-500">Projects define a persistent scope. Actions create traceable artifacts instead of another disconnected chat.</p>
          </div>
          <span className="inline-flex w-fit items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-[10px] font-semibold text-emerald-700"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />Research ready</span>
        </div>
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,.86fr)_minmax(0,1.14fr)] lg:p-5">
          <ResearchProjectPanel workspace={workspace} compact />
          <div className="rounded-[18px] border border-slate-200/70 bg-slate-50/55 p-5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-slate-400">Start a task</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">Use the current project scope. Choose one outcome rather than starting a generic agent chat.</p>
            <div className="mt-4"><ResearchWorkflowActions compact variant="inline" /></div>
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,.92fr)_minmax(0,1.08fr)]">
        <ResearchScopePanel workspace={workspace} />
        <KnowledgeResearchBridgePanel workspace={workspace} previewLimit={3} />
      </div>

      <ResearchLayer icon={<BookOpenCheck size={15} />} title="Evidence review & literature synthesis" description="Review persistent claims and generate a grounded synthesis when you need it.">
        <EvidenceReviewPanel workspace={workspace} />
      </ResearchLayer>

      <ResearchLayer icon={<FileText size={15} />} title="Writing drafts" description="Create, revise, and export versioned outlines and manuscript sections.">
        <WritingDraftPanel workspaceId={workspace.activeResearchWorkspaceId} />
      </ResearchLayer>

      <ResearchLayer icon={<NotebookText size={15} />} title="Research notes & source records" description="Browse captured evidence and personal annotations without crowding the active project flow.">
        <ResearchWorkspace />
      </ResearchLayer>
    </div>
  )
}

function ResearchLayer({
  children,
  description,
  icon,
  title,
}: {
  children: ReactNode
  description: string
  icon: ReactNode
  title: string
}) {
  return (
    <details className="group overflow-hidden rounded-[18px] border border-slate-200/70 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.04)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 transition hover:bg-slate-50/70 lg:px-6">
        <span className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-slate-500">{icon}</span>
          <span className="min-w-0"><span className="block text-sm font-semibold text-slate-800">{title}</span><span className="mt-0.5 block truncate text-[11px] text-slate-500">{description}</span></span>
        </span>
        <ChevronDown size={16} className="shrink-0 text-slate-400 transition group-open:rotate-180" />
      </summary>
      <div className="border-t border-slate-100 bg-slate-50/35 p-3 sm:p-4">{children}</div>
    </details>
  )
}

function SkeletonBlock({ className }: { className: string }) {
  return (
    <div className={`overflow-hidden rounded-[16px] border border-slate-200/60 bg-slate-50/60 p-4 ${className}`}>
      <div className="ait-skeleton h-4 w-24 rounded-full" />
      <div className="ait-skeleton mt-5 h-10 w-full rounded-[10px]" />
      <div className="ait-skeleton mt-3 h-10 w-[86%] rounded-[10px]" />
      <div className="ait-skeleton mt-3 h-24 w-full rounded-[14px]" />
    </div>
  )
}
