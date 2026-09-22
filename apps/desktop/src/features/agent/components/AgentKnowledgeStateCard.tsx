import { BrainCircuit, CheckCircle2, CircleDashed, Loader2, Search } from "lucide-react"

import type {
  AgentContextMode,
  AgentTraceEvent,
  KnowledgeAccessPolicy,
} from "../../../api/agent"
import { deriveAgentKnowledgeState } from "../runtime/agent-knowledge-state"

export function AgentKnowledgeStateCard({
  events,
  pending,
  policy = "auto",
  contextMode,
  contextTitle,
  contextSection,
  documentCount = 0,
  researchSourceCount = 0,
  workspaceSelected = false,
}: {
  events: AgentTraceEvent[]
  pending: boolean
  policy?: KnowledgeAccessPolicy
  contextMode?: AgentContextMode
  contextTitle?: string
  contextSection?: string
  documentCount?: number
  researchSourceCount?: number
  workspaceSelected?: boolean
}) {
  const state = deriveAgentKnowledgeState({
    events,
    pending,
    policy,
    contextMode,
    contextTitle,
    contextSection,
    documentCount,
    researchSourceCount,
    workspaceSelected,
  })

  const statusTone = state.status === "skipped"
    ? "border-slate-200 bg-slate-50 text-slate-600"
    : state.status === "evaluating"
      ? "border-amber-200 bg-amber-50 text-amber-700"
      : state.status === "retrieval_required" || state.status === "retrieved"
        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
        : "border-slate-200 bg-white text-slate-500"

  return (
    <section className="ait-surface p-4" aria-label="Agent knowledge state">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px] bg-slate-100 text-slate-700">
            <BrainCircuit size={17} />
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Knowledge access
            </p>
            <h3 className="mt-1 truncate text-sm font-semibold text-slate-900">Agent policy and scope</h3>
          </div>
        </div>
        <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-semibold text-slate-600">
          Agent · {state.policyLabel}
        </span>
      </div>

      <dl className="mt-4 grid gap-2 sm:grid-cols-2">
        <div className="rounded-[14px] border border-slate-200/80 bg-white/75 px-3 py-2.5">
          <dt className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge policy</dt>
          <dd className="mt-1 text-sm font-semibold text-slate-800">{state.policyLabel}</dd>
        </div>
        <div className="rounded-[14px] border border-slate-200/80 bg-white/75 px-3 py-2.5">
          <dt className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Scope</dt>
          <dd className="mt-1 truncate text-sm font-semibold text-slate-800" title={state.scopeDisplay}>
            {state.scopeDisplay}
          </dd>
        </div>
      </dl>

      <div className={`mt-3 flex items-center gap-3 rounded-[14px] border px-3 py-2.5 ${statusTone}`} aria-live="polite">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/80">
          {state.status === "evaluating" ? <Loader2 size={15} className="animate-spin" /> : null}
          {state.status === "retrieval_required" ? <Search size={15} /> : null}
          {state.status === "retrieved" ? <CheckCircle2 size={15} /> : null}
          {state.status === "skipped" ? <CircleDashed size={15} /> : null}
          {state.status === "idle" ? <CircleDashed size={15} /> : null}
        </span>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em]">Knowledge</p>
          <p className="mt-0.5 truncate text-xs font-semibold" title={state.statusDetail}>{state.statusDetail}</p>
        </div>
      </div>
    </section>
  )
}
