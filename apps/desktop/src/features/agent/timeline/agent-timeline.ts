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
  plan_ready: "decision",
  react_started: "decision",
  decision_ready: "decision",
  tool_call: "tool",
  retry: "tool",
  tool_result: "observation",
  observation_ready: "observation",
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
