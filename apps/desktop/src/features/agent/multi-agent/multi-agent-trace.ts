import type { MultiAgentRunTrace, MultiAgentTraceEvent } from "../../../api/agent-multi-agent"

export type MultiAgentNodeId =
  | "supervisor"
  | "knowledge"
  | "shared_context"
  | "research"
  | "reading"
  | "translation"

export type MultiAgentNodeStatus =
  | "idle"
  | "running"
  | "complete"
  | "warning"
  | "failed"
  | "skipped"

export interface MultiAgentNodeState {
  id: MultiAgentNodeId
  label: string
  description: string
  status: MultiAgentNodeStatus
  eventCount: number
  lastEvent?: MultiAgentTraceEvent
}

const NODE_META: Record<MultiAgentNodeId, Pick<MultiAgentNodeState, "label" | "description">> = {
  supervisor: {
    label: "Supervisor",
    description: "Plans the request and coordinates specialized agents.",
  },
  knowledge: {
    label: "Knowledge Retrieval",
    description: "Retrieves grounded evidence before specialist execution.",
  },
  shared_context: {
    label: "Shared Context",
    description: "Carries knowledge, citations, memory, and intermediate results.",
  },
  research: {
    label: "Research",
    description: "Handles literature and research-oriented tasks.",
  },
  reading: {
    label: "Reading",
    description: "Analyzes documents, sections, and reading context.",
  },
  translation: {
    label: "Translation",
    description: "Handles context-aware translation tasks.",
  },
}

const NODE_IDS = Object.keys(NODE_META) as MultiAgentNodeId[]

function normalizeStatus(status: string): MultiAgentNodeStatus {
  if (status === "running") return "running"
  if (status === "complete") return "complete"
  if (status === "warning") return "warning"
  if (status === "failed") return "failed"
  return "idle"
}

export function deriveMultiAgentNodeStates(trace: MultiAgentRunTrace | null): MultiAgentNodeState[] {
  const plannedAgents = new Set(trace?.plan.map((step) => step.agent) ?? [])

  return NODE_IDS.map((id) => {
    const events = trace?.events.filter((event) => event.actor === id) ?? []
    const lastEvent = events.at(-1)
    let status: MultiAgentNodeStatus = lastEvent ? normalizeStatus(lastEvent.status) : "idle"

    if (trace && ["research", "reading", "translation"].includes(id) && !plannedAgents.has(id)) {
      status = "skipped"
    }

    return {
      id,
      ...NODE_META[id],
      status,
      eventCount: events.length,
      lastEvent,
    }
  })
}

export function multiAgentEventLabel(event: MultiAgentTraceEvent): string {
  return event.event_type
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}
