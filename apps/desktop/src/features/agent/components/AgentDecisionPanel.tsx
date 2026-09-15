import {
  CheckCircle2,
  LoaderCircle,
  RotateCcw,
  ShieldAlert,
  TriangleAlert,
  XCircle,
} from "lucide-react"

import { AITPanel } from "@/shared/components/AITPanel"
import type { AgentDecisionNotice } from "../decision/agent-decision"

function panelClass(notice: AgentDecisionNotice): string {
  if (notice.tone === "danger") return "border-rose-200 bg-rose-50/80"
  if (notice.tone === "warning") return "border-amber-200 bg-amber-50/80"
  return "border-slate-200 bg-slate-50/80"
}

function iconClass(notice: AgentDecisionNotice): string {
  if (notice.tone === "danger") return "text-rose-700"
  if (notice.tone === "warning") return "text-amber-700"
  return "text-slate-600"
}

function DecisionIcon({ notice }: { notice: AgentDecisionNotice }) {
  const className = `shrink-0 ${iconClass(notice)}`
  if (notice.kind === "confirmation") return <ShieldAlert size={19} className={className} />
  if (notice.kind === "retry") return <RotateCcw size={18} className={className} />
  if (notice.kind === "cancelling") return <LoaderCircle size={18} className={`${className} animate-spin`} />
  if (notice.kind === "failure") return <XCircle size={19} className={className} />
  return <TriangleAlert size={19} className={className} />
}

export function AgentDecisionPanel({
  notice,
  onConfirm,
  confirming,
}: {
  notice: AgentDecisionNotice | null
  onConfirm: () => void
  confirming: boolean
}) {
  if (!notice) return null

  return (
    <AITPanel className={`border p-0 ${panelClass(notice)}`}>
      <div
        className="flex items-start gap-3 px-4 py-4 sm:px-5"
        data-agent-decision={notice.kind}
        role={notice.tone === "danger" ? "alert" : "status"}
      >
        <DecisionIcon notice={notice} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-950">{notice.title}</p>
            <span className="rounded-full border border-black/5 bg-white/70 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-500">
              Agent decision
            </span>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">{notice.detail}</p>

          {notice.toolName ? (
            <p className="mt-2 font-mono text-[10px] text-slate-500">tool: {notice.toolName}</p>
          ) : null}

          {notice.requiresConfirmation ? (
            <button
              type="button"
              onClick={onConfirm}
              disabled={confirming}
              className="mt-3 inline-flex items-center gap-2 rounded-[11px] bg-slate-950 px-3 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {confirming ? <LoaderCircle size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {confirming ? "Confirming…" : "Approve and execute"}
            </button>
          ) : null}
        </div>
      </div>
    </AITPanel>
  )
}

export default AgentDecisionPanel
