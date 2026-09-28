import { apiGet } from "./client"

export interface AgentCatalogEntry {
  agent_id: string
  name: string
  description: string
  capabilities: string[]
  version: string
  icon: string
}

export interface AgentCatalogResponse {
  agents: AgentCatalogEntry[]
}

export interface AgentRuntimeDebugRunSummary {
  run_id: string
  trace_id: string
  task_id: string | null
  status: string
  engine: string | null
  graph_version: string | null
  state_schema_version: number | null
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  event_count: number | null
  failure_reason: string | null
  recovery_reason: string | null
}

export interface AgentRuntimeDebugArtifactRef {
  artifact_id: string
  version: number | null
  kind: string | null
  content_hash: string | null
}

export interface AgentRuntimeDebugAttempt {
  attempt: number | null
  status: string | null
  duration_ms: number | null
  error_code: string | null
}

export interface AgentRuntimeDebugTask {
  task_id: string
  agent_id: string | null
  status: string | null
  depends_on: string[] | null
  required: boolean | null
  output_kind: string | null
  attempts: AgentRuntimeDebugAttempt[] | null
  artifact_refs: AgentRuntimeDebugArtifactRef[] | null
  duration_ms: number | null
  failure_reason: string | null
}

export interface AgentRuntimeDebugEvent {
  event_id: string
  sequence: number
  event_type: string
  timestamp: string
  task_id: string | null
  agent_id: string | null
  agent_version: string | null
  node_name: string | null
  subgraph_path: string | null
  status: string | null
  attempt: number | null
  duration_ms: number | null
  tool_name: string | null
  reason_code: string | null
  recovery_reason: string | null
}

export interface AgentRuntimeDebugRunDetail extends AgentRuntimeDebugRunSummary {
  route: {
    lane: string | null
    route_kind: string | null
    reason_code: string | null
  } | null
  plan: {
    plan_id: string | null
    plan_revision: number | null
    task_count: number | null
  } | null
  tasks: AgentRuntimeDebugTask[] | null
  tool_names: string[] | null
  related_ids: {
    rag_query_ids: string[] | null
    sandbox_ids: string[] | null
  }
  events: AgentRuntimeDebugEvent[]
}

export function getAgentCatalog(): Promise<AgentCatalogResponse> {
  return apiGet<AgentCatalogResponse>("/api/agent/catalog")
}

export function getAgentRuntimeDebugRuns(limit = 100): Promise<AgentRuntimeDebugRunSummary[]> {
  return apiGet<AgentRuntimeDebugRunSummary[]>(`/api/agent/runtime/debug/runs?limit=${limit}`)
}

export function getAgentRuntimeDebugRun(runId: string): Promise<AgentRuntimeDebugRunDetail> {
  return apiGet<AgentRuntimeDebugRunDetail>(
    `/api/agent/runtime/debug/runs/${encodeURIComponent(runId)}`,
  )
}
