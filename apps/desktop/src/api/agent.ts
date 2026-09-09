import { apiPost } from "./client"
import type { ReadingContextFields } from "./types"
import type { AgentCitationRef, AgentEvidenceItem } from "../features/evidence/evidence-types"

export type { AgentCitationRef, AgentEvidenceItem } from "../features/evidence/evidence-types"

export type AgentRunStatus = "completed" | "confirmation_required"
export type AgentPlanAction = "answer" | "tool"
export type AgentPlanMode = "none" | "single_step" | "multi_step"
export type AgentStepStatus = "pending" | "running" | "completed" | "failed" | "skipped"
export type AgentToolEffect = "read" | "compute" | "write"
export type AgentClientSurface = "main" | "overlay" | "unknown"
export type AgentTraceEventType =
  | "agent_start"
  | "context_ready"
  | "knowledge_retrieval_started"
  | "knowledge_retrieved"
  | "knowledge_context_ready"
  | "multi_agent_started"
  | "multi_agent_plan_ready"
  | "multi_agent_knowledge_started"
  | "multi_agent_knowledge_ready"
  | "multi_agent_context_ready"
  | "multi_agent_specialist_started"
  | "multi_agent_specialist_completed"
  | "multi_agent_specialist_failed"
  | "multi_agent_specialist_skipped"
  | "multi_agent_completed"
  | "plan_ready"
  | "react_started"
  | "decision_ready"
  | "tool_call"
  | "retry"
  | "tool_result"
  | "observation_ready"
  | "evidence_gate_evaluated"
  | "react_limit_reached"
  | "rag_query_started"
  | "rag_query_rewritten"
  | "rag_dense_completed"
  | "rag_sparse_completed"
  | "rag_fusion_completed"
  | "rag_rerank_completed"
  | "rag_evidence_selected"
  | "rag_fallback"
  | "synthesis_ready"
  | "grounding_verification_evaluated"
  | "failure"
  | "cancelled"
  | "agent_end"

export interface AgentPlan {
  action: AgentPlanAction
  tool_name: string
  user_visible_reason: string
  arguments: Record<string, string>
}

export interface AgentPlanStep {
  step_id: string
  tool_name: string
  arguments: Record<string, unknown>
  depends_on: string[]
  status: AgentStepStatus
}

export interface AgentMultiStepPlan {
  goal: string
  mode: AgentPlanMode
  steps: AgentPlanStep[]
  current_step_id: string
}

export interface AgentToolExecuteResponse {
  tool_name: string
  output_text: string
  effect: AgentToolEffect
  provider: string
  model: string
  request_id: number
  data: Record<string, unknown>
}

export interface AgentRunRequest extends ReadingContextFields {
  session_id: string
  trace_id?: string
  client_id?: string
  client_surface?: AgentClientSurface
  user_message: string
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  style?: string
  conversation_id?: string
  workspace_id?: string
  confirmed_write_tools?: string[]
  knowledge_document_ids?: string[]
  research_source_ids?: string[]
  request_id?: number
}

export interface AgentRunResponse {
  status: AgentRunStatus
  plan: AgentPlan
  multi_step_plan?: AgentMultiStepPlan | null
  output_text: string
  provider: string
  model: string
  request_id: number
  conversation_id: string
  tool_result: AgentToolExecuteResponse | null
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
}

export interface AgentTraceEvent {
  sequence: number
  event_type: AgentTraceEventType
  timestamp: string
  run_id: string
  trace_id: string
  elapsed_ms: number
  payload: Record<string, unknown>
}

export interface AgentRunTraceResponse {
  run_id: string
  trace_id: string
  session_id: string
  ui_mode: string
  total_duration_ms: number
  run: AgentRunResponse
  events: AgentTraceEvent[]
}

export function runAgentTrace(payload: AgentRunRequest): Promise<AgentRunTraceResponse> {
  return apiPost<AgentRunTraceResponse, AgentRunRequest>("/api/agent/run/trace", payload)
}
