import { useEffect, useMemo, useState } from "react"
import { Activity, Clock3, Cpu, RefreshCcw, RotateCcw, ShieldCheck } from "lucide-react"

import {
  getAgentObservabilitySummary,
  getRecentAgentRuns,
  type AgentObservabilitySummary,
  type AgentRunMetric,
} from "../../../api/agent-observability"
import {
  getAgentRuntimeConfig,
  type AgentRuntimeConfig,
} from "../../../api/agent-runtime-config"
import { AITPanel } from "@/shared/components/AITPanel"

function percentage(value: number): string {
  return `${Math.round(value * 100)}%`
}

function duration(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${Math.round(value)} ms`
}

function compactId(value: string): string {
  if (!value) return "—"
  return value.length <= 18 ? value : `${value.slice(0, 9)}…${value.slice(-6)}`
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[14px] border border-slate-100 bg-slate-50/70 px-3.5 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  )
}

type ObservabilitySnapshot = {
  refreshToken: number
  summary: AgentObservabilitySummary | null
  runs: AgentRunMetric[]
  runtimeConfig: AgentRuntimeConfig | null
  errorMessage: string
}

const EMPTY_SNAPSHOT: ObservabilitySnapshot = {
  refreshToken: -1,
  summary: null,
  runs: [],
  runtimeConfig: null,
  errorMessage: "",
}

export function AgentObservabilityPanel({
  refreshToken,
  currentRunId,
}: {
  refreshToken: number
  currentRunId: string
}) {
  const [snapshot, setSnapshot] = useState<ObservabilitySnapshot>(EMPTY_SNAPSHOT)

  useEffect(() => {
    let cancelled = false
    void Promise.all([
      getAgentObservabilitySummary(100),
      getRecentAgentRuns(6),
      getAgentRuntimeConfig(),
    ])
      .then(([summary, runs, runtimeConfig]) => {
        if (cancelled) return
        setSnapshot({
          refreshToken,
          summary,
          runs,
          runtimeConfig,
          errorMessage: "",
        })
      })
      .catch((error) => {
        if (cancelled) return
        setSnapshot((current) => ({
          ...current,
          refreshToken,
          errorMessage: error instanceof Error ? error.message : "Unable to load Agent metrics.",
        }))
      })

    return () => {
      cancelled = true
    }
  }, [refreshToken])

  const { summary, runs, runtimeConfig, errorMessage } = snapshot
  const loading = snapshot.refreshToken !== refreshToken
  const current = useMemo(
    () => runs.find((run) => run.run_id === currentRunId) ?? null,
    [currentRunId, runs],
  )
  const visibleRoutes = useMemo(
    () => runtimeConfig?.model_routes.filter((route) =>
      ["planner", "agent_synthesis", "reading"].includes(route.role),
    ) ?? [],
    [runtimeConfig],
  )
  const visiblePrompts = useMemo(
    () => runtimeConfig?.prompts.filter((prompt) =>
      ["agent.planner", "chat.reading"].includes(prompt.name),
    ) ?? [],
    [runtimeConfig],
  )

  return (
    <AITPanel className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Activity size={16} />
            Agent Observability
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Local, redacted runtime metrics. Reading text and model output are not persisted here.
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <RefreshCcw size={12} className={loading ? "animate-spin" : ""} />
          {summary ? `${summary.sample_size} runs` : "No sample"}
        </div>
      </div>

      {errorMessage ? (
        <div className="mt-4 rounded-[12px] border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {errorMessage}
        </div>
      ) : null}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <Metric label="Success" value={summary ? percentage(summary.success_rate) : "—"} />
        <Metric label="Schema valid" value={summary ? percentage(summary.schema_valid_rate) : "—"} />
        <Metric label="P95 latency" value={summary ? duration(summary.p95_total_duration_ms) : "—"} />
        <Metric label="Retry rate" value={summary ? percentage(summary.retry_rate) : "—"} />
        <Metric label="Fallback rate" value={summary ? percentage(summary.fallback_rate) : "—"} />
      </div>

      {runtimeConfig ? (
        <div className="mt-4 rounded-[14px] border border-slate-100 bg-white p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
              <Cpu size={14} />
              Runtime routing
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
              <ShieldCheck size={12} />
              {runtimeConfig.document_content_trust} · {runtimeConfig.planner_argument_policy}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {visibleRoutes.map((route) => (
              <span
                key={route.role}
                className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600"
                title={`${route.provider} · ${route.model}`}
              >
                {route.role}: <span className="font-medium text-slate-800">{route.model}</span>
              </span>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-400">
            {visiblePrompts.map((prompt) => (
              <span key={prompt.prompt_id} title={prompt.prompt_id}>
                {prompt.name} v{prompt.version}
              </span>
            ))}
            <span>planner budget {runtimeConfig.planner_context_max_chars.toLocaleString()} chars</span>
            <span>chat budget {runtimeConfig.chat_context_max_chars.toLocaleString()} chars</span>
          </div>
        </div>
      ) : null}

      {current ? (
        <div className="mt-4 grid gap-2 rounded-[14px] border border-slate-100 bg-white p-3 md:grid-cols-4">
          <div>
            <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">Current run</p>
            <p className="mt-1 font-mono text-xs text-slate-700" title={current.run_id}>
              {compactId(current.run_id)}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">Status</p>
            <p className="mt-1 text-xs font-medium text-slate-700">{current.status}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">Tool</p>
            <p className="mt-1 truncate text-xs font-medium text-slate-700">{current.tool_name || "direct answer"}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">Duration</p>
            <p className="mt-1 text-xs font-medium text-slate-700">{duration(current.total_duration_ms)}</p>
          </div>
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        {runs.length === 0 && !loading ? (
          <div className="rounded-[14px] border border-dashed border-slate-200 px-4 py-4 text-xs text-slate-500">
            Run the Agent to build a local reliability sample.
          </div>
        ) : (
          runs.map((run) => (
            <div
              key={run.run_id}
              className="grid gap-2 rounded-[12px] border border-slate-100 bg-slate-50/60 px-3 py-2.5 text-xs md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto_auto] md:items-center"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-slate-700">{run.intent || run.tool_name || "agent run"}</p>
                <p className="mt-0.5 truncate font-mono text-[10px] text-slate-400" title={run.trace_id}>
                  {compactId(run.trace_id)}
                </p>
              </div>
              <div className="flex items-center gap-1.5 text-slate-500">
                <Clock3 size={12} />
                {duration(run.total_duration_ms)}
              </div>
              <div className="flex items-center gap-1.5 text-slate-500">
                <RotateCcw size={12} />
                {run.retry_count}
              </div>
              <div className="flex items-center gap-1.5 text-slate-500">
                <ShieldCheck size={12} />
                {run.failure_count === 0 ? run.status : `${run.failure_count} failure`}
              </div>
            </div>
          ))
        )}
      </div>
    </AITPanel>
  )
}
