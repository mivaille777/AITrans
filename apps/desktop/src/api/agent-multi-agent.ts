import { apiPost } from "./client"

export interface MultiAgentPlanStep {
  agent: string
}

export interface MultiAgentResult {
  agent_name: string
  output: unknown
  metadata: Record<string, unknown>
}

export interface MultiAgentTraceEvent {
  sequence: number
  event_type: string
  actor: string
  status: string
  timestamp: string
  elapsed_ms: number
  payload: Record<string, unknown>
}

export interface MultiAgentContextSnapshot {
  knowledge_context_chars: number
  citation_count: number
  citations: Array<Record<string, unknown>>
  memory_keys: string[]
  intermediate_agents: string[]
}

export interface MultiAgentRunTrace {
  run_id: string
  trace_id: string
  total_duration_ms: number
  plan: MultiAgentPlanStep[]
  results: MultiAgentResult[]
  context: MultiAgentContextSnapshot
  events: MultiAgentTraceEvent[]
}

export interface MultiAgentRunRequest {
  task: string
  user_id?: string
}

export function runMultiAgentTrace(request: MultiAgentRunRequest): Promise<MultiAgentRunTrace> {
  return apiPost<MultiAgentRunTrace, MultiAgentRunRequest>(
    "/api/agent/multi-agent/run/trace",
    request,
  )
}
