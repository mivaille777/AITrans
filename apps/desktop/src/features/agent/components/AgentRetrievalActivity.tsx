import { Check, LoaderCircle, Search, TriangleAlert } from "lucide-react"

import type { AgentActivityItem } from "../state/agent-workspace-state"

const retrievalTypes = [
  "rag_query_rewritten",
  "rag_dense_completed",
  "rag_sparse_completed",
  "rag_fusion_completed",
  "rag_rerank_completed",
  "rag_evidence_selected",
] as const

const labels: Record<(typeof retrievalTypes)[number], string> = {
  rag_query_rewritten: "Query rewrite",
  rag_dense_completed: "Dense retrieval",
  rag_sparse_completed: "Sparse retrieval",
  rag_fusion_completed: "Fusion",
  rag_rerank_completed: "Reranking",
  rag_evidence_selected: "Evidence selected",
}

export function AgentRetrievalActivity({ activities, running }: { activities: AgentActivityItem[]; running: boolean }) {
  const started = activities.find((item) => item.eventType === "rag_query_started")
  const fallback = activities.find((item) => item.eventType === "rag_fallback")
  const steps = retrievalTypes.flatMap((type) => {
    const item = activities.find((activity) => activity.eventType === type)
    return item ? [{ type, item }] : []
  })
  if (!started && steps.length === 0 && !fallback) return null

  return (
    <section className="mt-5 rounded-[16px] border border-cyan-100 bg-cyan-50/35 p-4" aria-label="Knowledge retrieval activity">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5"><span className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-[10px] bg-white text-cyan-700 shadow-sm"><Search size={14} /></span><div><h3 className="text-xs font-semibold text-slate-800">search_knowledge_base</h3><p className="mt-0.5 text-[10px] text-slate-500">{started?.detail || "Local hybrid retrieval"}</p></div></div>
        {running && !fallback && steps.at(-1)?.type !== "rag_evidence_selected" ? <span className="flex items-center gap-1 text-[10px] text-cyan-700"><LoaderCircle size={11} className="animate-spin" />Retrieving</span> : null}
      </div>

      <ol className="mt-4 space-y-1.5 border-l border-cyan-200/80 pl-4">
        {steps.map(({ type, item }) => (
          <li key={type} className="relative rounded-[12px] border border-white/80 bg-white/75 px-3 py-2.5">
            <span className="absolute -left-[21px] top-3 flex h-3 w-3 items-center justify-center rounded-full bg-emerald-500 text-white ring-2 ring-cyan-50"><Check size={8} /></span>
            <div className="flex items-center justify-between gap-3"><strong className="text-[11px] font-semibold text-slate-700">{labels[type]}</strong><span className="text-[10px] tabular-nums text-slate-400">{durationFrom(item.detail)}</span></div>
            <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{withoutDuration(item.detail)}</p>
          </li>
        ))}
        {fallback && <li className="relative rounded-[12px] border border-amber-100 bg-amber-50/90 px-3 py-2.5"><span className="absolute -left-[22px] top-3 flex h-4 w-4 items-center justify-center rounded-full bg-amber-400 text-white ring-2 ring-cyan-50"><TriangleAlert size={9} /></span><strong className="text-[11px] font-semibold text-amber-800">Retrieval fallback</strong><p className="mt-0.5 text-[10px] leading-4 text-amber-700">{fallback.detail}</p></li>}
      </ol>
    </section>
  )
}

function durationFrom(detail: string): string {
  const match = detail.match(/·\s*([\d.]+\s*ms)$/)
  return match?.[1] ?? ""
}

function withoutDuration(detail: string): string {
  return detail.replace(/\s*·\s*[\d.]+\s*ms$/, "")
}
