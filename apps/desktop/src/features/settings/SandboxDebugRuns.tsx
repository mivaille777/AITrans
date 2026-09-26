import { AlertCircle, LoaderCircle, RefreshCw } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  getSandboxDebugRun,
  listSandboxDebugRuns,
  type SandboxDebugTrace,
  type SandboxRunStatus,
  type SandboxRunSummary,
} from "../../api/sandbox-debug"

type StatusFilter = "all" | SandboxRunStatus
type SourceFilter = "all" | "agent" | "manual"

export default function SandboxDebugRuns({
  onSelectTrace,
}: {
  onSelectTrace: (trace: SandboxDebugTrace) => void
}) {
  const [runs, setRuns] = useState<SandboxRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [selectingId, setSelectingId] = useState("")
  const [error, setError] = useState("")
  const [status, setStatus] = useState<StatusFilter>("all")
  const [source, setSource] = useState<SourceFilter>("all")
  const [workspace, setWorkspace] = useState("all")
  const [query, setQuery] = useState("")

  async function refresh() {
    setLoading(true)
    setError("")
    try {
      setRuns(await listSandboxDebugRuns())
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Unable to load Sandbox runs.")
    } finally {
      setLoading(false)
    }
  }

  /* oxlint-disable react-hooks/exhaustive-deps -- initial run history load is intentionally one-shot */
  useEffect(() => {
    void refresh()
  }, [])
  /* oxlint-enable react-hooks/exhaustive-deps */

  const workspaces = useMemo(
    () => [...new Set(runs.map((run) => run.workspace_name).filter(Boolean))].sort(),
    [runs],
  )

  const filteredRuns = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return runs.filter((run) => {
      if (status !== "all" && run.status !== status) return false
      if (source !== "all" && run.source !== source) return false
      if (workspace !== "all" && run.workspace_name !== workspace) return false
      if (!normalized) return true
      return [run.sandbox_id, run.run_id, run.tool_call_id]
        .some((value) => value.toLowerCase().includes(normalized))
    })
  }, [query, runs, source, status, workspace])

  async function inspect(run: SandboxRunSummary) {
    if (selectingId) return
    setSelectingId(run.sandbox_id)
    setError("")
    try {
      onSelectTrace(await getSandboxDebugRun(run.sandbox_id))
    } catch (inspectError) {
      setError(inspectError instanceof Error ? inspectError.message : "Unable to load Sandbox trace.")
    } finally {
      setSelectingId("")
    }
  }

  return (
    <div className="h-full overflow-auto bg-slate-50/40 px-8 py-6">
      <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-4">
        <section className="rounded-[10px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Run History</p>
              <h2 className="mt-1 text-[15px] font-semibold text-slate-900">Sandbox executions</h2>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              className="inline-flex w-fit items-center gap-1.5 rounded-[7px] border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>

          <div className="grid gap-2 border-b border-slate-100 px-5 py-3 sm:grid-cols-2 lg:grid-cols-4">
            <select aria-label="Run status" value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} className="h-8 rounded-[7px] border border-slate-200 bg-white px-2 text-[10px] text-slate-600">
              <option value="all">All statuses</option>
              {["completed","failed","cancelled","timed_out","output_limit_exceeded","oom_killed","pending","preparing","running"].map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <select aria-label="Run source" value={source} onChange={(event) => setSource(event.target.value as SourceFilter)} className="h-8 rounded-[7px] border border-slate-200 bg-white px-2 text-[10px] text-slate-600">
              <option value="all">All sources</option>
              <option value="agent">Agent</option>
              <option value="manual">Manual</option>
            </select>
            <select aria-label="Run workspace" value={workspace} onChange={(event) => setWorkspace(event.target.value)} className="h-8 rounded-[7px] border border-slate-200 bg-white px-2 text-[10px] text-slate-600">
              <option value="all">All workspaces</option>
              {workspaces.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <input aria-label="Search runs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="sandbox / run / tool id" className="h-8 rounded-[7px] border border-slate-200 bg-white px-2.5 text-[10px] text-slate-600 outline-none focus:border-slate-400" />
          </div>

          {error ? (
            <div className="flex items-center gap-2 border-b border-rose-100 bg-rose-50 px-5 py-2.5 text-[10px] text-rose-700" role="alert">
              <AlertCircle size={12} />
              {error}
            </div>
          ) : null}

          {loading ? (
            <div className="flex items-center justify-center gap-2 px-5 py-12 text-[11px] text-slate-400">
              <LoaderCircle size={14} className="animate-spin" />
              Loading Sandbox runs…
            </div>
          ) : filteredRuns.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <h3 className="text-[13px] font-semibold text-slate-800">No sandbox runs recorded</h3>
              <p className="mt-1 text-[11px] text-slate-400">Run history will appear here after Sandbox execution.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-slate-100 text-[9px] uppercase tracking-[0.09em] text-slate-400">
                    <th className="px-5 py-2.5 font-medium">Status</th>
                    <th className="px-3 py-2.5 font-medium">Source</th>
                    <th className="px-3 py-2.5 font-medium">Workspace</th>
                    <th className="px-3 py-2.5 font-medium">Runtime</th>
                    <th className="px-3 py-2.5 font-medium">Duration</th>
                    <th className="px-3 py-2.5 font-medium">Started</th>
                    <th className="px-5 py-2.5 font-medium">Sandbox</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRuns.map((run) => (
                    <tr key={run.sandbox_id} className="border-b border-slate-100 text-[10px] text-slate-600 last:border-b-0">
                      <td className="px-5 py-3"><StatusBadge status={run.status} /></td>
                      <td className="px-3 py-3 capitalize">{run.source}</td>
                      <td className="px-3 py-3">{run.workspace_name || "—"}</td>
                      <td className="px-3 py-3">{run.runtime}</td>
                      <td className="px-3 py-3">{formatDuration(run.duration_ms)}</td>
                      <td className="px-3 py-3">{formatStarted(run.started_at)}</td>
                      <td className="px-5 py-3">
                        <button
                          type="button"
                          onClick={() => void inspect(run)}
                          disabled={Boolean(selectingId)}
                          className="inline-flex items-center gap-1.5 font-mono text-[9px] font-medium text-slate-700 underline decoration-slate-300 underline-offset-2 hover:text-slate-950 disabled:opacity-50"
                        >
                          {selectingId === run.sandbox_id ? <LoaderCircle size={10} className="animate-spin" /> : null}
                          {run.sandbox_id}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: SandboxRunStatus }) {
  const className = status === "completed"
    ? "bg-emerald-50 text-emerald-700"
    : ["failed","timed_out","output_limit_exceeded","oom_killed"].includes(status)
      ? "bg-rose-50 text-rose-700"
      : status === "cancelled"
        ? "bg-slate-100 text-slate-600"
        : "bg-amber-50 text-amber-800"
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[9px] font-semibold ${className}`}>{status}</span>
}

function formatDuration(value: number): string {
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(2)} s`
}

function formatStarted(value: string): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}
