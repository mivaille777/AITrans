import { LoaderCircle, ServerOff } from "lucide-react"

import { EmptyState } from "../../shared/ui/EmptyState"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
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
      <ResearchProjectPanel workspace={workspace} />
      <EvidenceReviewPanel workspace={workspace} />
      <KnowledgeResearchBridgePanel workspace={workspace} />
      <ResearchScopePanel workspace={workspace} />
      <WritingDraftPanel workspaceId={workspace.activeResearchWorkspaceId} />
      <ResearchWorkspace />
    </div>
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
