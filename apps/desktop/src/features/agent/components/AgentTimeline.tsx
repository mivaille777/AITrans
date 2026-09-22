import { Check, Circle, LoaderCircle, TriangleAlert } from "lucide-react"

import { AITPanel } from "@/shared/components/AITPanel"
import type { AgentActivityItem } from "../state/agent-workspace-state"
import { AgentRetrievalActivity } from "./AgentRetrievalActivity"
import {
  deriveAgentTimelineHierarchy,
  deriveAgentTimelineStages,
  getAgentTimelineEventLabel,
  type AgentTimelineStageStatus,
} from "../timeline/agent-timeline"

function StageIcon({ status }: { status: AgentTimelineStageStatus }) {
  if (status === "active") return <LoaderCircle size={13} className="animate-spin" />
  if (status === "complete") return <Check size={13} />
  if (status === "warning") return <TriangleAlert size={13} />
  return <Circle size={11} />
}

function stageClass(status: AgentTimelineStageStatus): string {
  if (status === "active") return "border-slate-300 bg-slate-950 text-white"
  if (status === "complete") return "border-emerald-200 bg-emerald-50/70 text-emerald-900"
  if (status === "warning") return "border-amber-200 bg-amber-50/80 text-amber-900"
  return "border-slate-200 bg-white/70 text-slate-400"
}

function activityToneClass(item: AgentActivityItem): string {
  if (item.tone === "warning") return "border-amber-200 bg-amber-50/70"
  if (item.tone === "success") return "border-emerald-100 bg-emerald-50/40"
  return "border-slate-100 bg-slate-50/70"
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function activityCopy(item: AgentActivityItem): { label: string; detail: string } {
  if (item.eventType !== "knowledge_context_ready") {
    return { label: item.label, detail: item.detail }
  }

  const payload = item.payload ?? {}
  const canvas = record(payload.canvas)
  const attached = record(payload.attached)
  const name = stringValue(canvas.board_name) || stringValue(canvas.scope_label) || "Knowledge context"
  const cards = numberValue(attached.cards)
  const relations = numberValue(attached.relations)
  const documents = numberValue(attached.documents)
  return {
    label: "Knowledge context attached",
    detail: `${name} · ${cards} cards · ${relations} relations · ${documents} documents`,
  }
}

export function AgentTimeline({
  activities,
  running,
  runId,
  traceId,
  totalDurationMs,
  runStatus = "",
}: {
  activities: AgentActivityItem[]
  running: boolean
  runId: string
  traceId: string
  totalDurationMs: number
  runStatus?: string
}) {
  const stages = deriveAgentTimelineStages(activities, running)
  const hierarchy = deriveAgentTimelineHierarchy(activities)

  return (
    <AITPanel className="min-h-0 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Execution Timeline
          </p>
          <p className="mt-1 text-sm font-medium text-slate-800">
            Decision → Action → Observation → Result
          </p>
          {runId || traceId ? (
            <p className="mt-1 max-w-[560px] truncate font-mono text-[10px] text-slate-400">
              {[runId, traceId].filter(Boolean).join(" · ")}
            </p>
          ) : null}
        </div>
        <div className="text-xs text-slate-500">
          {running ? (
            <span className="inline-flex items-center gap-1.5">
              <LoaderCircle size={12} className="animate-spin" />
              {runStatus ? runStatus.replaceAll("_", " ") : "Running"}
            </span>
          ) : runStatus ? (
            <span className="capitalize">{runStatus.replaceAll("_", " ")}</span>
          ) : totalDurationMs > 0 ? (
            <span>{totalDurationMs} ms</span>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Agent execution stages">
        {stages.map((stage, index) => (
          <div
            key={stage.id}
            data-agent-timeline-stage={stage.id}
            data-stage-status={stage.status}
            className={`rounded-[14px] border px-3 py-3 ${stageClass(stage.status)}`}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-semibold tabular-nums opacity-60">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <strong className="text-xs font-semibold">{stage.label}</strong>
              </div>
              <StageIcon status={stage.status} />
            </div>
            <p className="mt-2 text-[10px] leading-4 opacity-75">{stage.description}</p>
            {stage.activityCount > 1 ? (
              <p className="mt-2 text-[10px] font-medium opacity-60">{stage.activityCount} events</p>
            ) : null}
          </div>
        ))}
      </div>


      {activities.length > 0 ? (
        <div className="mt-4 rounded-[16px] border border-slate-200/80 bg-slate-50/55 p-3" aria-label="Run step tool hierarchy">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
            <span className="rounded-full border border-slate-200 bg-white px-2 py-1">Run</span>
            <span className="font-mono normal-case tracking-normal text-slate-500">{runId || "current"}</span>
          </div>
          <div className="mt-3 space-y-2 border-l border-slate-200 pl-3">
            {hierarchy.map((step) => (
              <div key={step.stepId} className="rounded-[12px] border border-slate-200/80 bg-white/85 px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-400">Step</span>
                  <span className="font-mono text-[10px] text-slate-700">{step.label}</span>
                  <span className={`ml-auto text-[9px] font-medium ${step.warning ? "text-amber-700" : "text-slate-400"}`}>
                    {step.eventCount} events
                  </span>
                </div>
                {step.tools.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5 border-l border-slate-100 pl-3">
                    {step.tools.map((tool) => (
                      <span
                        key={tool.toolCallId}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 font-mono text-[9px] ${
                          tool.warning
                            ? "border-amber-200 bg-amber-50 text-amber-800"
                            : "border-slate-200 bg-slate-50 text-slate-600"
                        }`}
                        title={tool.toolCallId}
                      >
                        Tool · {tool.toolName}
                        <span className="text-slate-400">({tool.eventCount})</span>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <AgentRetrievalActivity activities={activities} running={running} />

      <div className="mt-5">
        {activities.length === 0 ? (
          <div className="rounded-[14px] border border-dashed border-slate-200 bg-slate-50/70 px-4 py-5 text-sm text-slate-500">
            Start an Agent task to see decisions, tool actions, observations, retries, and the final result here.
          </div>
        ) : (
          <ol className="ait-scroll-panel max-h-[420px] space-y-2 overflow-y-auto overscroll-contain pr-1" aria-label="Agent runtime events">
            {activities.map((item) => {
              const copy = activityCopy(item)
              return (
                <li
                  key={`${item.sequence}-${item.eventType}`}
                  className={`rounded-[14px] border px-3.5 py-3 ${activityToneClass(item)}`}
                >
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-6 min-w-6 items-center justify-center rounded-full border border-white/80 bg-white text-[10px] font-semibold tabular-nums text-slate-500 shadow-sm">
                      {item.sequence + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-slate-200/80 bg-white/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                          {getAgentTimelineEventLabel(item.eventType)}
                        </span>
                        <p className="text-sm font-medium text-slate-800">{copy.label}</p>
                      </div>
                      <p className="mt-1 break-words text-xs leading-5 text-slate-500">{copy.detail}</p>
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </AITPanel>
  )
}

export default AgentTimeline
