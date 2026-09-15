import type { AgentTraceEvent } from "../../../api/agent"

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
  lastEvent?: AgentTraceEvent
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
const MULTI_AGENT_PREFIX = "multi_agent_"

export function isMultiAgentTraceEvent(event: AgentTraceEvent): boolean {
  return event.event_type.startsWith(MULTI_AGENT_PREFIX)
}

function eventActor(event: AgentTraceEvent): string {
  return String(event.payload.actor ?? "").trim()
}

function normalizeStatus(status: unknown, eventType: string): MultiAgentNodeStatus {
  const value = String(status ?? "").trim()
  if (value === "running") return "running"
  if (value === "complete") return "complete"
  if (value === "warning") return "warning"
  if (value === "failed") return "failed"
  if (eventType.endsWith("_failed")) return "failed"
  if (eventType.endsWith("_skipped")) return "skipped"
  if (eventType.endsWith("_completed") || eventType.endsWith("_ready")) return "complete"
  return "idle"
}

function plannedAgents(events: AgentTraceEvent[]): Set<string> {
  const planEvent = events.find((event) => event.event_type === "multi_agent_plan_ready")
  const raw = planEvent?.payload.agents
  if (!Array.isArray(raw)) return new Set()
  return new Set(raw.map((item) => String(item ?? "").trim()).filter(Boolean))
}

export function deriveMultiAgentNodeStates(events: AgentTraceEvent[]): MultiAgentNodeState[] {
  const multiAgentEvents = events.filter(isMultiAgentTraceEvent)
  const planned = plannedAgents(multiAgentEvents)
  const collaborationStarted = multiAgentEvents.length > 0

  return NODE_IDS.map((id) => {
    const nodeEvents = multiAgentEvents.filter((event) => eventActor(event) === id)
    const lastEvent = nodeEvents.at(-1)
    let status: MultiAgentNodeStatus = lastEvent
      ? normalizeStatus(lastEvent.payload.status, lastEvent.event_type)
      : "idle"

    if (
      collaborationStarted
      && ["research", "reading", "translation"].includes(id)
      && !planned.has(id)
      && nodeEvents.length === 0
    ) {
      status = "skipped"
    }

    return {
      id,
      ...NODE_META[id],
      status,
      eventCount: nodeEvents.length,
      lastEvent,
    }
  })
}

export function multiAgentEventLabel(event: AgentTraceEvent): string {
  return event.event_type
    .replace(/^multi_agent_/, "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}
