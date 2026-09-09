import { useMemo, useState } from "react"
import {
  BookOpenText,
  Check,
  Circle,
  Database,
  Languages,
  LoaderCircle,
  Network,
  Play,
  Search,
  Share2,
  TriangleAlert,
  X,
} from "lucide-react"

import {
  runMultiAgentTrace,
  type MultiAgentRunTrace,
} from "../../../api/agent-multi-agent"
import { AITPanel } from "@/shared/components/AITPanel"
import {
  deriveMultiAgentNodeStates,
  multiAgentEventLabel,
  type MultiAgentNodeId,
  type MultiAgentNodeState,
  type MultiAgentNodeStatus,
} from "../multi-agent/multi-agent-trace"

const NODE_ICONS: Record<MultiAgentNodeId, typeof Network> = {
  supervisor: Network,
  knowledge: Database,
  shared_context: Share2,
  research: Search,
  reading: BookOpenText,
  translation: Languages,
}

function nodeTone(status: MultiAgentNodeStatus): string {
  if (status === "running") return "border-slate-300 bg-slate-950 text-white"
  if (status === "complete") return "border-emerald-200 bg-emerald-50/70 text-emerald-950"
  if (status === "warning") return "border-amber-200 bg-amber-50/80 text-amber-950"
  if (status === "failed") return "border-rose-200 bg-rose-50/80 text-rose-950"
  if (status === "skipped") return "border-slate-100 bg-slate-50/70 text-slate-400"
  return "border-slate-200 bg-white/80 text-slate-700"
}

function StatusIcon({ status }: { status: MultiAgentNodeStatus }) {
  if (status === "running") return <LoaderCircle size={13} className="animate-spin" />
  if (status === "complete") return <Check size={13} />
  if (status === "warning") return <TriangleAlert size={13} />
  if (status === "failed") return <X size={13} />
  return <Circle size={10} />
}

function AgentNode({ node }: { node: MultiAgentNodeState }) {
  const Icon = NODE_ICONS[node.id]
  return (
    <div
      data-multi-agent-node={node.id}
      data-node-status={node.status}
      className={`min-w-0 rounded-[16px] border px-4 py-3.5 transition-colors ${nodeTone(node.status)}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-current/10 bg-white/60">
            <Icon size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold">{node.label}</p>
            <p className="mt-0.5 text-[10px] uppercase tracking-[0.12em] opacity-55">
              {node.status}
            </p>
          </div>
        </div>
        <StatusIcon status={node.status} />
      </div>
      <p className="mt-3 text-[11px] leading-5 opacity-70">{node.description}</p>
      {node.lastEvent ? (
        <p className="mt-2 truncate text-[10px] opacity-55">
          {multiAgentEventLabel(node.lastEvent)} · {node.lastEvent.elapsed_ms} ms
        </p>
      ) : null}
    </div>
  )
}

function compactId(value: string): string {
  if (!value) return "—"
  return value.length <= 22 ? value : `${value.slice(0, 10)}…${value.slice(-7)}`
}

export function MultiAgentTracePanel({ task }: { task: string }) {
  const [trace, setTrace] = useState<MultiAgentRunTrace | null>(null)
  const [pending, setPending] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")
  const nodes = useMemo(() => deriveMultiAgentNodeStates(trace), [trace])
  const nodeMap = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.id, node])) as Record<MultiAgentNodeId, MultiAgentNodeState>,
    [nodes],
  )
  const normalizedTask = task.trim()

  async function runTrace() {
    if (!normalizedTask || pending) return
    setPending(true)
    setErrorMessage("")
    try {
      setTrace(await runMultiAgentTrace({ task: normalizedTask }))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the multi-agent trace.")
    } finally {
      setPending(false)
    }
  }

  return (
    <AITPanel className="p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Network size={16} />
            Multi-Agent Execution
          </div>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
            Supervisor planning, grounded knowledge retrieval, shared context propagation, and specialized Agent execution in one trace.
          </p>
        </div>
        <button
          type="button"
          onClick={runTrace}
          disabled={!normalizedTask || pending}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-[12px] border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45"
          title={normalizedTask ? "Run the current prompt through the Stage 5 multi-agent trace" : "Enter an Agent prompt first"}
        >
          {pending ? <LoaderCircle size={14} className="animate-spin" /> : <Play size={14} />}
          {pending ? "Running" : trace ? "Run again" : "Run collaboration"}
        </button>
      </div>

      {errorMessage ? (
        <div className="mt-4 rounded-[12px] border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {errorMessage}
        </div>
      ) : null}

      <div className="mt-5" aria-label="Multi-agent execution graph">
        <div className="mx-auto max-w-md">
          <AgentNode node={nodeMap.supervisor} />
        </div>

        <div className="mx-auto h-5 w-px bg-slate-200" aria-hidden="true" />

        <div className="grid gap-3 lg:grid-cols-2">
          <AgentNode node={nodeMap.knowledge} />
          <AgentNode node={nodeMap.shared_context} />
        </div>

        <div className="mx-auto h-5 w-px bg-slate-200" aria-hidden="true" />

        <div className="grid gap-3 md:grid-cols-3">
          <AgentNode node={nodeMap.research} />
          <AgentNode node={nodeMap.reading} />
          <AgentNode node={nodeMap.translation} />
        </div>
      </div>

      {trace ? (
        <>
          <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-[13px] border border-slate-100 bg-slate-50/70 px-3.5 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Duration</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">{trace.total_duration_ms} ms</p>
            </div>
            <div className="rounded-[13px] border border-slate-100 bg-slate-50/70 px-3.5 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Knowledge</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">{trace.context.citation_count} citations</p>
            </div>
            <div className="rounded-[13px] border border-slate-100 bg-slate-50/70 px-3.5 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Context</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">{trace.context.knowledge_context_chars} chars</p>
            </div>
            <div className="rounded-[13px] border border-slate-100 bg-slate-50/70 px-3.5 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Specialists</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">{trace.results.length} executed</p>
            </div>
          </div>

          {trace.context.citations.length > 0 ? (
            <div className="mt-4 rounded-[14px] border border-slate-100 bg-white p-3.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Retrieved evidence</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {trace.context.citations.slice(0, 8).map((citation, index) => (
                  <span
                    key={`${String(citation.id ?? "source")}-${index}`}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600"
                  >
                    {String(citation.title || citation.id || `Source ${index + 1}`)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mt-4 rounded-[14px] border border-slate-100 bg-slate-50/50 p-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">Multi-Agent Trace</p>
              <p className="font-mono text-[10px] text-slate-400" title={`${trace.run_id} · ${trace.trace_id}`}>
                {compactId(trace.run_id)} · {compactId(trace.trace_id)}
              </p>
            </div>
            <ol className="mt-3 space-y-2" aria-label="Multi-agent trace events">
              {trace.events.map((event) => (
                <li key={`${event.sequence}-${event.event_type}`} className="flex items-start gap-3 text-xs">
                  <span className="mt-0.5 flex h-5 min-w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-[9px] font-semibold tabular-nums text-slate-400">
                    {event.sequence + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-slate-700">{event.actor}</span>
                      <span className="text-slate-500">{multiAgentEventLabel(event)}</span>
                      <span className="text-[10px] tabular-nums text-slate-400">{event.elapsed_ms} ms</span>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-[14px] border border-dashed border-slate-200 bg-slate-50/60 px-4 py-4 text-xs leading-5 text-slate-500">
          Enter an Agent prompt, then run the collaboration trace to see which specialist Agents are selected and how Knowledge Runtime feeds the shared context.
        </div>
      )}
    </AITPanel>
  )
}

export default MultiAgentTracePanel
