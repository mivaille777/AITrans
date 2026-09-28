import { useCallback, useEffect, useMemo, useState } from "react"
import { Activity, Bot, CircleAlert, Clock3, RefreshCw, Wrench } from "lucide-react"

import {
  getAgentCatalog,
  getAgentRuntimeDebugRun,
  getAgentRuntimeDebugRuns,
  type AgentCatalogEntry,
  type AgentRuntimeDebugRunDetail,
  type AgentRuntimeDebugRunSummary,
} from "../../api/agent-runtime-debug"

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  waiting: "等待确认",
  confirmation_required: "等待确认",
  pause_requested: "正在暂停",
  paused: "已暂停",
  recovering: "恢复中",
  recovered: "已恢复",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
}

function missing(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "未记录" : String(value)
}

function displayStatus(status: string, detail?: AgentRuntimeDebugRunDetail | null): string {
  if (status === "waiting" && detail?.events.some((event) => event.event_type === "write_confirmation_required")) {
    return "等待写入确认"
  }
  if (detail?.events.some((event) => event.event_type === "workflow_resumed")) return "已恢复"
  return statusLabels[status] ?? status
}

function displayTaskStatus(status: string | null): string {
  if (!status) return "未记录"
  return statusLabels[status] ?? status
}

export default function RuntimeDebugStudio({ initialRunId = "" }: { initialRunId?: string }) {
  const [runs, setRuns] = useState<AgentRuntimeDebugRunSummary[]>([])
  const [agents, setAgents] = useState<AgentCatalogEntry[]>([])
  const [selectedRunId, setSelectedRunId] = useState(initialRunId)
  const [loadedDetail, setLoadedDetail] = useState<AgentRuntimeDebugRunDetail | null>(null)
  const [loadedDetailRunId, setLoadedDetailRunId] = useState("")
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [error, setError] = useState("")

  const requestRuns = useCallback(() => Promise.all([getAgentRuntimeDebugRuns(), getAgentCatalog()]), [])

  const refreshRuns = useCallback(async () => {
    setLoadingRuns(true)
    setError("")
    try {
      const [nextRuns, catalog] = await requestRuns()
      setRuns(nextRuns)
      setAgents(catalog.agents)
      setSelectedRunId((current) => current || initialRunId || nextRuns[0]?.run_id || "")
    } catch {
      setError("无法读取 Agent Runtime Debug 数据。")
    } finally {
      setLoadingRuns(false)
    }
  }, [initialRunId, requestRuns])

  useEffect(() => {
    let active = true
    void requestRuns()
      .then(([nextRuns, catalog]) => {
        if (!active) return
        setRuns(nextRuns)
        setAgents(catalog.agents)
        setSelectedRunId((current) => current || initialRunId || nextRuns[0]?.run_id || "")
      })
      .catch(() => { if (active) setError("无法读取 Agent Runtime Debug 数据。") })
      .finally(() => { if (active) setLoadingRuns(false) })
    return () => { active = false }
  }, [initialRunId, requestRuns])

  useEffect(() => {
    if (!selectedRunId) return
    let active = true
    void getAgentRuntimeDebugRun(selectedRunId)
      .then((next) => {
        if (!active) return
        setLoadedDetail(next)
        setLoadedDetailRunId(selectedRunId)
      })
      .catch(() => {
        if (!active) return
        setLoadedDetail(null)
        setLoadedDetailRunId(selectedRunId)
      })
    return () => { active = false }
  }, [selectedRunId])

  const detail = loadedDetail?.run_id === selectedRunId ? loadedDetail : null
  const loadingDetail = Boolean(selectedRunId) && loadedDetailRunId !== selectedRunId
  const agentsById = useMemo(() => new Map(agents.map((agent) => [agent.agent_id, agent])), [agents])
  const sharedLanguageTools = detail?.tool_names?.filter((name) => /translate|polish|language/i.test(name)) ?? []

  return (
    <div className="h-full min-h-0 overflow-auto bg-white px-5 py-5" aria-label="Agent Runtime Debug Studio">
      <div className="mx-auto max-w-[1240px] space-y-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">AITrans / Settings</p>
            <h1 className="mt-1 text-lg font-semibold text-slate-950">Agent Runtime Debug</h1>
            <p className="mt-1 text-[11px] text-slate-500">只读查看 Run、Plan、任务尝试、工具名称和安全 Artifact 引用。</p>
          </div>
          <button type="button" onClick={() => void refreshRuns()} disabled={loadingRuns} className="inline-flex h-8 items-center gap-1.5 rounded-[8px] border border-slate-200 px-2.5 text-[10px] font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            <RefreshCw size={13} className={loadingRuns ? "animate-spin" : ""} />刷新
          </button>
        </header>

        {error ? <p role="alert" className="rounded-[9px] border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">{error}</p> : null}

        <div className="grid min-h-[420px] gap-3 xl:grid-cols-[280px_minmax(0,1fr)]">
          <section className="overflow-hidden rounded-[10px] border border-slate-200" aria-label="Runtime runs">
            <div className="border-b border-slate-100 px-3 py-2.5 text-[11px] font-semibold text-slate-800">Runs</div>
            <div className="max-h-[640px] overflow-y-auto p-1.5">
              {loadingRuns ? <p className="px-2 py-4 text-[10px] text-slate-400">加载中…</p> : null}
              {!loadingRuns && runs.length === 0 ? <p className="px-2 py-4 text-[10px] text-slate-400">暂无 Run 记录</p> : null}
              {runs.map((run) => (
                <button key={run.run_id} type="button" onClick={() => setSelectedRunId(run.run_id)} aria-pressed={selectedRunId === run.run_id} className={`mb-1 block w-full rounded-[8px] px-2.5 py-2 text-left ${selectedRunId === run.run_id ? "bg-slate-100" : "hover:bg-slate-50"}`}>
                  <span className="block truncate font-mono text-[10px] font-medium text-slate-800">{run.run_id}</span>
                  <span className="mt-1 flex items-center justify-between gap-2 text-[9px] text-slate-500"><span>{statusLabels[run.status] ?? run.status}</span><span>{missing(run.duration_ms)}{run.duration_ms === null ? "" : " ms"}</span></span>
                </button>
              ))}
            </div>
          </section>

          <section className="min-w-0 space-y-3 rounded-[10px] border border-slate-200 p-3.5" aria-label="Runtime run detail">
            {!selectedRunId ? <div className="py-10 text-center text-[11px] text-slate-400">选择一个 Run 查看详情</div> : null}
            {selectedRunId && loadingDetail ? <div className="py-10 text-center text-[11px] text-slate-400">读取安全投影…</div> : null}
            {selectedRunId && !loadingDetail && !detail ? <div className="py-10 text-center text-[11px] text-slate-400">该 Run 暂无可用详情</div> : null}
            {detail ? <>
              <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 pb-3">
                <div className="min-w-0"><p className="font-mono text-[11px] font-semibold text-slate-900">{detail.run_id}</p><p className="mt-1 text-[10px] text-slate-500">Trace {missing(detail.trace_id)} · Task {missing(detail.task_id)}</p></div>
                <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-700">{displayStatus(detail.status, detail)}</span>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <Metric label="Route" value={detail.route?.route_kind ?? detail.route?.lane} />
                <Metric label="Plan" value={detail.plan?.plan_id} />
                <Metric label="Plan revision" value={detail.plan?.plan_revision} />
                <Metric label="Duration" value={detail.duration_ms === null ? null : `${detail.duration_ms} ms`} />
                <Metric label="Engine" value={detail.engine} />
                <Metric label="Graph version" value={detail.graph_version} />
                <Metric label="Failure reason" value={detail.failure_reason} />
                <Metric label="Recovery reason" value={detail.recovery_reason} />
              </div>

              <div className="grid gap-3 lg:grid-cols-2">
                <section className="rounded-[8px] border border-slate-100 p-3">
                  <h2 className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-800"><Bot size={13} />Agent tasks</h2>
                  {!detail.tasks?.length ? <p className="mt-2 text-[10px] text-slate-400">未记录任务 Plan</p> : <div className="mt-2 space-y-2">{detail.tasks.map((task) => {
                    const agent = task.agent_id ? agentsById.get(task.agent_id) : undefined
                    return <article key={task.task_id} className="rounded-[7px] bg-slate-50 px-2.5 py-2" data-task-id={task.task_id}>
                      <div className="flex flex-wrap justify-between gap-2"><span className="text-[10px] font-medium text-slate-800">{agent?.name ?? task.agent_id ?? "Agent 未记录"}</span><span className="text-[9px] text-slate-500">{displayTaskStatus(task.status)}</span></div>
                      <p className="mt-1 break-all font-mono text-[9px] text-slate-400">{task.task_id}</p>
                      <p className="mt-1 text-[9px] text-slate-500">依赖：{task.depends_on?.join("、") || (task.depends_on ? "无" : "未记录")} · 尝试：{task.attempts?.length ?? "未记录"} · 用时：{task.duration_ms === null ? "未记录" : `${task.duration_ms} ms`}</p>
                      {task.failure_reason ? <p className="mt-1 flex items-center gap-1 text-[9px] text-rose-700"><CircleAlert size={10} />{task.failure_reason}</p> : null}
                      {task.artifact_refs?.length ? <p className="mt-1 break-all text-[9px] text-slate-500">ArtifactRefs：{task.artifact_refs.map((ref) => `${ref.artifact_id}@${missing(ref.version)}`).join(" · ")}</p> : <p className="mt-1 text-[9px] text-slate-400">ArtifactRefs：未记录</p>}
                    </article>
                  })}</div>}
                </section>

                <section className="rounded-[8px] border border-slate-100 p-3">
                  <h2 className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-800"><Wrench size={13} />Tool capabilities</h2>
                  {detail.tool_names?.length ? <p className="mt-2 break-words text-[10px] text-slate-700">{detail.tool_names.join(" · ")}</p> : <p className="mt-2 text-[10px] text-slate-400">Tool 名称未记录</p>}
                  {sharedLanguageTools.length ? <p className="mt-2 rounded-[7px] bg-violet-50 px-2.5 py-2 text-[9px] text-violet-800">共享语言 Capability · {sharedLanguageTools.join("、")} · 不作为独立 Agent</p> : null}
                  <div className="mt-3 border-t border-slate-100 pt-2 text-[9px] text-slate-500">RAG query IDs：{detail.related_ids.rag_query_ids?.join("、") || "未记录"}</div>
                  <div className="mt-1 text-[9px] text-slate-500">Sandbox IDs：{detail.related_ids.sandbox_ids?.join("、") || "未记录"}</div>
                </section>
              </div>

              <section className="rounded-[8px] border border-slate-100 p-3">
                <h2 className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-800"><Activity size={13} />Event sequence</h2>
                {!detail.events.length ? <p className="mt-2 text-[10px] text-slate-400">未记录事件</p> : <ol className="mt-2 max-h-[320px] space-y-1.5 overflow-auto">{detail.events.map((event) => <li key={event.event_id} className="grid gap-1 rounded-[6px] bg-slate-50 px-2 py-1.5 text-[9px] sm:grid-cols-[48px_minmax(100px,1fr)_minmax(120px,2fr)_auto]">
                  <span className="font-mono text-slate-400">#{event.sequence}</span>
                  <span className="font-medium text-slate-700">{event.event_type}</span>
                  <span className="truncate text-slate-500">{event.node_name ?? event.agent_id ?? event.task_id ?? "未记录"}</span>
                  <span className="flex items-center gap-1 text-slate-400"><Clock3 size={10} />{event.duration_ms === null ? "未记录" : `${event.duration_ms} ms`}</span>
                </li>)}</ol>}
              </section>
            </> : null}
          </section>
        </div>
        <p className="text-[9px] text-slate-400">该面板为只读投影；文本、完整工具参数、checkpoint 内容和 Artifact 正文不会显示。</p>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number | null | undefined }) {
  return <div className="rounded-[7px] bg-slate-50 px-2.5 py-2"><p className="text-[8px] uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 break-all text-[10px] font-medium text-slate-700">{missing(value)}</p></div>
}
