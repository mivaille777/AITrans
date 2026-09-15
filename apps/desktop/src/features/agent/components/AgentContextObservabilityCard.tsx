import type { AgentKnowledgeContext, AgentTraceEvent } from "../../../api/agent"
import { resolveKnowledgeContextObservability } from "../runtime/agent-context-observability"

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[14px] border border-slate-200/80 bg-white/80 px-3 py-2.5">
      <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-semibold tabular-nums text-slate-800">{value}</p>
    </div>
  )
}

function Visibility({ label, ready }: { label: string; ready: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 text-[11px]">
      <span className="text-slate-500">{label}</span>
      <span className={ready ? "font-medium text-emerald-600" : "font-medium text-slate-400"}>
        {ready ? "Ready" : "Awaiting runtime"}
      </span>
    </div>
  )
}

export function AgentContextObservabilityCard({
  context,
  events,
}: {
  context: AgentKnowledgeContext | null
  events: AgentTraceEvent[]
}) {
  const diagnostics = resolveKnowledgeContextObservability({ context, events })
  if (!diagnostics) return null

  const synthesis = diagnostics.synthesis
  const statusLabel = diagnostics.status === "runtime_confirmed"
    ? "Runtime confirmed"
    : "Attached · awaiting run"
  const budgetLabel = synthesis && synthesis.maxChars > 0
    ? `${synthesis.usedChars.toLocaleString()} / ${synthesis.maxChars.toLocaleString()} chars`
    : "Available after runtime confirmation"
  const truncationLabel = !synthesis
    ? "Pending"
    : synthesis.truncated
      ? [
          synthesis.cardsDropped > 0 ? `${synthesis.cardsDropped} cards dropped` : "",
          synthesis.cardSummariesCompacted > 0 ? `${synthesis.cardSummariesCompacted} summaries compacted` : "",
          synthesis.relationsDropped > 0 ? `${synthesis.relationsDropped} relations dropped` : "",
        ].filter(Boolean).join(" · ") || "Context compacted"
      : "No truncation"

  return (
    <section className="ait-surface p-4 sm:p-5" aria-label="Knowledge context observability">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Knowledge Context
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-slate-900">{diagnostics.canvasName}</h3>
            <span className={diagnostics.status === "runtime_confirmed"
              ? "rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700"
              : "rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500"}
            >
              {statusLabel}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Binding: <span className="font-medium text-slate-700">{diagnostics.binding}</span>
          </p>
        </div>
        <p className="max-w-sm text-right text-[10px] leading-4 text-slate-400">
          Canvas relations describe knowledge structure. They are not treated as document evidence by themselves.
        </p>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric label="Cards" value={String(diagnostics.cards)} />
        <Metric label="Relations" value={String(diagnostics.relations)} />
        <Metric label="Documents" value={String(diagnostics.documents)} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-[14px] border border-slate-200/80 bg-slate-50/70 p-3">
          <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Runtime visibility</p>
          <div className="mt-2 space-y-1.5">
            <Visibility label="Planner" ready={diagnostics.visibility.planner} />
            <Visibility label="ReAct decision" ready={diagnostics.visibility.react} />
            <Visibility label="Final synthesis" ready={diagnostics.visibility.synthesis} />
          </div>
        </div>

        <div className="rounded-[14px] border border-slate-200/80 bg-slate-50/70 p-3">
          <p className="text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">Synthesis context budget</p>
          <p className="mt-2 text-xs font-semibold tabular-nums text-slate-800">{budgetLabel}</p>
          <p className={synthesis?.truncated ? "mt-1 text-[10px] leading-4 text-amber-600" : "mt-1 text-[10px] leading-4 text-slate-500"}>
            {truncationLabel}
          </p>
          {synthesis ? (
            <p className="mt-1 text-[10px] leading-4 text-slate-400">
              Prompt projection: {synthesis.cardsIncluded}/{diagnostics.cards} cards · {synthesis.relationsIncluded}/{diagnostics.relations} relations. Relations are budgeted before long card summaries.
            </p>
          ) : null}
        </div>
      </div>
    </section>
  )
}
