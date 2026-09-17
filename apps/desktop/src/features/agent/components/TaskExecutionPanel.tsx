import { AlertTriangle, CheckCircle2, Circle, Languages, LoaderCircle, RotateCcw, XCircle } from "lucide-react"

import type { AgentRunSnapshot, AgentTaskSpec, AgentTraceEvent } from "../../../api/agent"
import { Button } from "../../../shared/ui/Button"
import { latestTaskEvent } from "../runtime/agent-event-replay"

const taskEventTypes = new Set([
  "task_planned", "task_ready", "task_started", "task_progress", "task_completed",
  "task_partial", "task_failed", "task_blocked", "task_cancelled", "task_skipped", "task_retrying",
])

const roleLabels: Record<string, string> = {
  document: "论文阅读",
  research: "研究综合",
  writer: "学术写作",
  curator: "笔记与图谱",
}

function eventTasks(events: AgentTraceEvent[]): AgentTaskSpec[] {
  const tasks = new Map<string, AgentTaskSpec>()
  for (const event of events) {
    if (event.event_type !== "task_planned") continue
    const taskId = String(event.payload.task_id ?? "").trim()
    if (!taskId || tasks.has(taskId)) continue
    tasks.set(taskId, {
      task_id: taskId,
      role: String(event.payload.role ?? event.payload.actor ?? "document") as AgentTaskSpec["role"],
      objective: "",
      depends_on: Array.isArray(event.payload.depends_on) ? event.payload.depends_on.map(String) : [],
      required: event.payload.required !== false,
      expected_output_kind: String(event.payload.output_kind ?? "artifact"),
      plan_revision: Number(event.payload.plan_revision ?? 1),
    })
  }
  return [...tasks.values()]
}

function taskStatus(taskId: string, events: AgentTraceEvent[], snapshot: AgentRunSnapshot | null): string {
  const result = snapshot?.results.find((item) => item.task_id === taskId)
  if (result) return result.status
  const event = latestTaskEvent(events, taskId)
  if (!event) return "pending"
  return String(event.payload.status ?? event.event_type.replace("task_", ""))
}

function tone(status: string): string {
  if (["succeeded", "completed"].includes(status)) return "border-emerald-200 bg-emerald-50/60"
  if (["failed", "blocked", "cancelled"].includes(status)) return "border-rose-200 bg-rose-50/60"
  if (status === "partial") return "border-amber-200 bg-amber-50/60"
  if (["running", "ready", "retrying"].includes(status)) return "border-cyan-200 bg-cyan-50/50"
  return "border-slate-200 bg-white"
}

function StatusIcon({ status }: { status: string }) {
  if (["running", "ready", "retrying"].includes(status)) return <LoaderCircle size={14} className="animate-spin text-cyan-700" />
  if (["succeeded", "completed"].includes(status)) return <CheckCircle2 size={14} className="text-emerald-700" />
  if (status === "partial") return <AlertTriangle size={14} className="text-amber-700" />
  if (["failed", "blocked", "cancelled"].includes(status)) return <XCircle size={14} className="text-rose-700" />
  return <Circle size={12} className="text-slate-300" />
}

export function TaskExecutionPanel({
  events,
  snapshot,
  running,
  onRetry,
}: {
  events: AgentTraceEvent[]
  snapshot: AgentRunSnapshot | null
  running: boolean
  onRetry: (taskId: string) => void
}) {
  const tasks = snapshot?.plan.tasks?.length ? snapshot.plan.tasks : eventTasks(events)
  const taskEvents = events.filter((event) => taskEventTypes.has(event.event_type))
  const languageCalls = events.filter((event) => event.event_type === "tool_call" && /translate|polish|language/i.test(String(event.payload.name ?? event.payload.tool_name ?? "")))
  if (tasks.length === 0) return null

  const failures = tasks.filter((task) => ["failed", "blocked", "partial"].includes(taskStatus(task.task_id, events, snapshot)))
  return (
    <section className="ait-surface p-5" aria-label="Task execution">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">真实任务计划</p>
          <p className="mt-1 text-xs text-slate-500">节点、依赖和终态来自后端 TaskPlan 与 run snapshot。</p>
        </div>
        <span className="text-[11px] text-slate-400">{running ? "执行中" : failures.length ? `${failures.length} 个任务需处理` : "已同步"}</span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {tasks.map((task) => {
          const status = taskStatus(task.task_id, events, snapshot)
          const retryable = snapshot?.retryable_task_ids.includes(task.task_id) ?? false
          const result = snapshot?.results.find((item) => item.task_id === task.task_id)
          return (
            <article key={task.task_id} className={`rounded-[15px] border p-3.5 ${tone(status)}`} data-task-id={task.task_id} data-task-status={status}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">{roleLabels[task.role] ?? task.role} · expert</p>
                  <h3 className="mt-1 text-xs font-semibold text-slate-800">{task.objective || `${task.expected_output_kind.replaceAll("_", " ")} deliverable`}</h3>
                </div>
                <StatusIcon status={status} />
              </div>
              <p className="mt-2 text-[10px] text-slate-500">状态：{status} · 尝试 {result?.attempt_ordinal ?? Number(latestTaskEvent(taskEvents, task.task_id)?.payload.attempt ?? 0)}</p>
              <p className="mt-1 text-[10px] text-slate-500">依赖：{task.depends_on.length ? task.depends_on.join("、") : "无"}</p>
              {result?.error_code ? <p className="mt-2 text-[10px] text-rose-700">{result.error_code}</p> : null}
              {retryable ? <Button className="mt-3" size="xs" onClick={() => onRetry(task.task_id)}><RotateCcw size={11} />重试失败任务</Button> : null}
            </article>
          )
        })}
      </div>

      {languageCalls.length ? (
        <div className="mt-3 flex items-center gap-2 rounded-[12px] border border-violet-100 bg-violet-50/60 px-3 py-2 text-[11px] text-violet-800">
          <Languages size={13} />共享语言工具 · 非独立专家 · {languageCalls.length} 次调用
        </div>
      ) : null}
    </section>
  )
}
