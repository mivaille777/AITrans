import { apiGet, apiPost } from "./client"
import type { ReadingContextFields } from "./types"
import type { AgentCitationRef, AgentEvidenceItem } from "../features/evidence/evidence-types"

export type { AgentCitationRef, AgentEvidenceItem } from "../features/evidence/evidence-types"

export type AgentRunStatus = "completed" | "confirmation_required"
export type AgentPlanAction = "answer" | "tool"
export type AgentPlanMode = "none" | "single_step" | "multi_step"
export type AgentStepStatus = "pending" | "running" | "completed" | "failed" | "skipped"
export type AgentToolEffect = "read" | "compute" | "write"
export type AgentClientSurface = "main" | "overlay" | "unknown"
export type AgentContextMode = "general" | "reading" | "knowledge" | "research" | "translation"
export type AgentWorkflowAction = "" | "quick_read" | "analyze_visuals" | "compare_papers" | "curate_knowledge" | "draft_section"
export type KnowledgeAccessPolicy = "auto" | "always" | "never"
export type KnowledgeScopeStrategy = "none" | "attached_document" | "explicit_documents" | "research_workspace" | "global_knowledge"

export interface AgentToolDefinition {
  name: string
  title: string
  description: string
  category: string
  effect: AgentToolEffect
  requires_reading_context: boolean
  requires_confirmation: boolean
  input_schema: Record<string, unknown>
}

export interface AgentToolCatalogResponse {
  tools: AgentToolDefinition[]
}

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
  | "task_planned"
  | "task_ready"
  | "task_started"
  | "task_progress"
  | "task_completed"
  | "task_partial"
  | "task_failed"
  | "task_blocked"
  | "task_cancelled"
  | "task_skipped"
  | "task_retrying"
  | "plan_revised"
  | "budget_exhausted"
  | "artifact_verified"
  | "artifact_rejected"
  | "workflow_partial"
  | "workflow_resumed"
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

export interface AgentKnowledgeCanvasContext {
  board_id: string
  board_name: string
  scope_label: string
}

export interface AgentKnowledgeCardContext {
  item_id: string
  item_type: string
  title: string
  summary: string
  document_id: string
}

export interface AgentKnowledgeRelationContext {
  relation_id: string
  source_item_id: string
  source_title: string
  target_item_id: string
  target_title: string
  relation_type: string
  label: string
  origin: string
  confidence: number | null
}

export interface AgentKnowledgeContext {
  canvas: AgentKnowledgeCanvasContext | null
  cards: AgentKnowledgeCardContext[]
  relations: AgentKnowledgeRelationContext[]
}

export interface AgentRunRequest extends ReadingContextFields {
  session_id: string
  trace_id?: string
  resume_run_id?: string
  client_id?: string
  client_surface?: AgentClientSurface
  context_mode?: AgentContextMode
  knowledge_access_policy?: KnowledgeAccessPolicy
  knowledge_enabled?: boolean
  user_message: string
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  style?: string
  conversation_id?: string
  workspace_id?: string
  confirmed_write_tools?: string[]
  enabled_tools?: string[]
  knowledge_document_ids?: string[]
  explicit_knowledge_document_ids?: string[]
  attached_document_id?: string
  research_source_ids?: string[]
  knowledge_context?: AgentKnowledgeContext | null
  request_id?: number
  temporary?: boolean
  workflow_action?: AgentWorkflowAction
  retry_task_id?: string
}

export interface AgentRunResponse {
  run_id: string
  trace_id: string
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
  task_id?: string
  step_id?: string
  tool_call_id?: string
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

export interface AgentTaskSpec {
  task_id: string
  role: "document" | "research" | "writer" | "curator"
  objective: string
  depends_on: string[]
  required: boolean
  expected_output_kind: string
  plan_revision: number
}

export interface AgentTaskResult {
  task_id: string
  attempt_id: string
  attempt_ordinal: number
  status: string
  artifact_refs: Array<{ artifact_id: string; version: number; kind: string; content_hash: string }>
  evidence_refs: Array<Record<string, unknown>>
  coverage?: number | null
  unmet_requirements: string[]
  warnings: string[]
  error_code: string
}

export interface AgentArtifact {
  artifact_id: string
  version: number
  producer_task_id: string
  kind: string
  scope_ref: string
  content: Record<string, unknown>
  evidence_refs: Array<Record<string, unknown>>
  source_coverage: { complete: boolean; covered_refs: string[]; missing_refs: string[]; notes: string[] }
  verification_status: string
  verification_report: { issues?: Array<{ code: string; severity: string; message: string; evidence_ids: string[] }> }
  [key: string]: unknown
}

export interface AgentRunSnapshot {
  run_id: string
  trace_id: string
  status: string
  scope: Record<string, unknown>
  plan: { plan_id?: string; plan_revision?: number; tasks?: AgentTaskSpec[] }
  results: AgentTaskResult[]
  artifacts: AgentArtifact[]
  events: AgentTraceEvent[]
  resumable: boolean
  retryable_task_ids: string[]
}

export function runAgentTrace(payload: AgentRunRequest): Promise<AgentRunTraceResponse> {
  return apiPost<AgentRunTraceResponse, AgentRunRequest>("/api/agent/run/trace", payload)
}

export function getAgentTools(): Promise<AgentToolCatalogResponse> {
  return apiGet<AgentToolCatalogResponse>("/api/agent/tools")
}

export function getAgentRunSnapshot(runId: string): Promise<AgentRunSnapshot> {
  return apiGet<AgentRunSnapshot>(`/api/agent/runs/${encodeURIComponent(runId)}/snapshot`)
}
