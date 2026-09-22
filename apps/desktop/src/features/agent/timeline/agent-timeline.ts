import type { AgentTraceEventType } from "../../../api/agent"
import type { AgentActivityItem } from "../state/agent-workspace-state"

export type AgentTimelineStageId = "decision" | "tool" | "observation" | "result"
export type AgentTimelineStageStatus = "idle" | "active" | "complete" | "warning"

export interface AgentTimelineStage {
  id: AgentTimelineStageId
  label: string
  description: string
  status: AgentTimelineStageStatus
  activityCount: number
}

export const agentTimelineStageDefinitions = [
  {
    id: "decision",
    label: "Decision",
    description: "Choose one bounded next action or finish.",
  },
  {
    id: "tool",
    label: "Action",
    description: "Execute the selected capability safely.",
  },
  {
    id: "observation",
    label: "Observation",
    description: "Return compact tool evidence to the Agent.",
  },
  {
    id: "result",
    label: "Result",
    description: "Synthesize or finish the run.",
  },
] as const

const eventStage: Partial<Record<AgentTraceEventType, AgentTimelineStageId>> = {
  task_planned: "decision",
  task_ready: "decision",
  plan_revised: "decision",
  task_started: "tool",
  task_progress: "tool",
  task_retrying: "tool",
  task_completed: "observation",
  task_partial: "observation",
  artifact_verified: "observation",
  artifact_rejected: "observation",
  task_failed: "result",
  task_blocked: "result",
  task_cancelled: "result",
  task_skipped: "result",
  budget_exhausted: "result",
  workflow_partial: "result",
  workflow_resumed: "decision",
  knowledge_decision: "decision",
  knowledge_scope_resolved: "decision",
  knowledge_retrieval_started: "observation",
  knowledge_retrieved: "observation",
  knowledge_skipped: "result",
  plan_ready: "decision",
  react_started: "decision",
  decision_ready: "decision",
  tool_call: "tool",
  retry: "tool",
  tool_result: "observation",
  observation_ready: "observation",
  evidence_gate_evaluated: "observation",
  evidence_sufficiency: "observation",
  rag_query_started: "observation",
  rag_query_rewritten: "observation",
  rag_dense_completed: "observation",
  rag_sparse_completed: "observation",
  rag_fusion_completed: "observation",
  rag_rerank_completed: "observation",
  rag_evidence_selected: "observation",
  rag_fallback: "observation",
  react_limit_reached: "result",
  synthesis_ready: "result",
  failure: "result",
  cancelled: "result",
  agent_end: "result",
}

const terminalEventTypes = new Set<AgentTraceEventType>([
  "failure",
  "cancelled",
  "task_cancelled",
  "workflow_partial",
  "agent_end",
])

export function getAgentTimelineStageId(
  eventType: AgentTraceEventType,
): AgentTimelineStageId | null {
  return eventStage[eventType] ?? null
}

export function getAgentTimelineEventLabel(eventType: AgentTraceEventType): string {
  if (
    eventType === "agent_start"
    || eventType === "context_ready"
    || eventType === "knowledge_context_ready"
  ) return "Setup"
  if (
    eventType === "knowledge_decision"
    || eventType === "knowledge_scope_resolved"
    || eventType === "knowledge_skipped"
  ) return "Knowledge"
  if (eventType === "evidence_gate_evaluated" || eventType === "evidence_sufficiency") return "Evidence"
  const stageId = getAgentTimelineStageId(eventType)
  return agentTimelineStageDefinitions.find((stage) => stage.id === stageId)?.label ?? "Runtime"
}

export function deriveAgentTimelineStages(
  activities: AgentActivityItem[],
  running: boolean,
): AgentTimelineStage[] {
  const primaryActivities = activities.filter((item) => getAgentTimelineStageId(item.eventType))
  const latestStageId = primaryActivities.length > 0
    ? getAgentTimelineStageId(primaryActivities.at(-1)!.eventType)
    : null
  const hasTerminalEvent = activities.some((item) => terminalEventTypes.has(item.eventType))

  return agentTimelineStageDefinitions.map((definition) => {
    const stageActivities = activities.filter(
      (item) => getAgentTimelineStageId(item.eventType) === definition.id,
    )
    const hasWarning = stageActivities.some((item) => item.tone === "warning")

    let status: AgentTimelineStageStatus = "idle"
    if (hasWarning) {
      status = "warning"
    } else if (stageActivities.length > 0) {
      status = running && !hasTerminalEvent && latestStageId === definition.id
        ? "active"
        : "complete"
    } else if (
      running
      && activities.length > 0
      && latestStageId === null
      && definition.id === "decision"
    ) {
      status = "active"
    }

    return {
      ...definition,
      status,
      activityCount: stageActivities.length,
    }
  })
}


export interface AgentTimelineToolGroup {
  toolCallId: string
  toolName: string
  eventCount: number
  warning: boolean
}

export interface AgentTimelineStepGroup {
  stepId: string
  label: string
  eventCount: number
  warning: boolean
  tools: AgentTimelineToolGroup[]
}

function payloadText(item: AgentActivityItem, key: string): string {
  const value = item.payload?.[key]
  return typeof value === "string" ? value.trim() : ""
}

export function deriveAgentTimelineHierarchy(
  activities: AgentActivityItem[],
): AgentTimelineStepGroup[] {
  const groups = new Map<string, AgentActivityItem[]>()
  for (const item of activities) {
    const stepId = item.stepId || payloadText(item, "step_id") || "runtime"
    const current = groups.get(stepId) ?? []
    current.push(item)
    groups.set(stepId, current)
  }

  return [...groups.entries()].map(([stepId, items]) => {
    const toolGroups = new Map<string, AgentActivityItem[]>()
    for (const item of items) {
      const toolCallId = item.toolCallId || payloadText(item, "tool_call_id")
      if (!toolCallId) continue
      const current = toolGroups.get(toolCallId) ?? []
      current.push(item)
      toolGroups.set(toolCallId, current)
    }
    return {
      stepId,
      label: stepId === "runtime" ? "Runtime lifecycle" : stepId,
      eventCount: items.length,
      warning: items.some((item) => item.tone === "warning"),
      tools: [...toolGroups.entries()].map(([toolCallId, toolEvents]) => ({
        toolCallId,
        toolName:
          toolEvents.map((item) => payloadText(item, "tool_name") || payloadText(item, "name"))
            .find(Boolean) || "tool",
        eventCount: toolEvents.length,
        warning: toolEvents.some((item) => item.tone === "warning"),
      })),
    }
  })
}
