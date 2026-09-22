import { apiDelete, apiGet, apiPatch, apiPost, apiWebSocketUrl } from "./client"

export type RagDebugRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled"
export type RagDebugStageStatus = "pending" | "active" | "complete" | "warning" | "failed" | "skipped"
export type RagDebugTab = "trace" | "retrieval" | "chunks" | "evaluation" | "compare" | "datasets"

export interface RagConfig {
  enabled: boolean
  advanced_parsing: Record<string, unknown>
  visual_understanding: Record<string, unknown>
  visual_retrieval: Record<string, unknown>
  chunking: Record<string, unknown>
  semantic_chunking: Record<string, unknown>
  embedding: Record<string, unknown>
  vector_store: Record<string, unknown>
  retrieval: {
    dense_top_k: number
    sparse_top_k: number
    fusion_top_k: number
    final_top_k: number
    fusion: string
    small_to_big_enabled: boolean
    small_to_big_top_k: number
    small_to_big_neighbor_radius: number
    small_to_big_max_tokens_per_anchor: number
  }
  reranker: Record<string, unknown>
}

export interface RagDebugCompanionTrace {
  trace_id: string
  request_id: number
  conversation_id: string
  query: string
  knowledge_enabled: boolean
  document_scope: string
  route: string
  route_reason: string
  grounding_policy: string
  retrieval_skipped: boolean
  verification_skipped: boolean
  catalog_document_count: number
  retrieval: Record<string, unknown>
  evidence: Array<Record<string, unknown>>
  citations: Array<Record<string, unknown>>
  verification: Record<string, unknown>
  fallback_applied: boolean
  created_at: string
}

export interface RagDebugConfigProfile {
  config_id: string
  name: string
  description: string
  config: RagConfig
  active: boolean
  requires_reindex: boolean
  index_fingerprint: string
  created_at: string
  updated_at: string
}

export interface RagDebugStage {
  key: string
  label: string
  status: RagDebugStageStatus
  elapsed_ms: number
  note: string
  summary: Record<string, unknown>
  candidate_count: number
}

export interface RagDebugCandidate {
  id: string
  document_id: string
  source: string
  section: string
  page: number | null
  tokens: number
  dense: number | null
  bm25: number | null
  fusion: number | null
  rerank: number | null
  before: number | null
  after: number | null
  text: string
  chunk_type: string
  start: number
  end: number
  metadata: Record<string, unknown>
}

export interface RagDebugTraceResponse {
  run_id: string
  trace_id: string
  status: RagDebugRunStatus
  query: string
  config_id: string
  query_plan: Record<string, unknown>
  stages: RagDebugStage[]
  candidates: RagDebugCandidate[]
  context: {
    text: string
    estimated_tokens: number
    included_evidence_ids: string[]
    omitted_evidence_ids: string[]
    source_count: number
  }
  evidence: Array<Record<string, unknown>>
  citations: Array<Record<string, unknown>>
  answer: string
  knowledge_decision: Record<string, unknown>
  knowledge_scope: Record<string, unknown>
  metadata: Record<string, unknown>
  error: string
}

export interface RagDebugStageEvent {
  sequence: number
  stage: string
  status: string
  elapsed_ms: number
  payload: Record<string, unknown>
}

export interface RagDebugDocument {
  document_id: string
  title: string
  source_uri: string
  status: string
  chunk_count: number
  updated_at: string
}

export interface RagDebugChunk {
  id: string
  document_id: string
  title: string
  preview: string
  section: string
  section_path: string[]
  page: number | null
  tokens: number
  overlap: number
  start: number
  end: number
  type: string
  embedding: string
  text: string
  metadata: Record<string, unknown>
}

export interface RagDebugChunkPage {
  chunks: RagDebugChunk[]
  total: number
  page: number
  page_size: number
}

export interface RagDebugDataset {
  dataset_id: string
  name: string
  description: string
  case_count: number
  created_at: string
  updated_at: string
}

export interface RagDebugCase {
  case_id: string
  query: string
  categories: string[]
  relevant_chunk_ids: string[]
  relevance_grades: Record<string, number>
  claims: Array<Record<string, unknown>>
  no_answer: boolean
  metadata: Record<string, string>
  query_type: string
  expected_answer: string
  answerable: boolean
  tags: string[]
  notes: string
  updated_at: string
}

export interface RagDebugEvaluationResponse {
  dataset_id: string
  config_id: string
  report: {
    total_cases: number
    retrieval: Record<string, number>
    reranker: Record<string, number>
    citations: Record<string, number>
    performance: Record<string, unknown>
    cases: Array<Record<string, unknown>>
    case_details?: Array<Record<string, unknown>>
    [key: string]: unknown
  }
}

export interface RagDebugCompareCase {
  case_id: string
  query: string
  baseline_rank: number | null
  candidate_rank: number | null
  baseline_latency_ms: number
  candidate_latency_ms: number
  baseline_chunk_ids: string[]
  candidate_chunk_ids: string[]
}

export interface RagDebugCompareResponse {
  dataset_id: string
  baseline_config_id: string
  candidate_config_id: string
  cases: RagDebugCompareCase[]
  metrics: Record<string, number>
}

export interface RagDebugRunAccepted {
  run_id: string
  trace_id: string
  status: RagDebugRunStatus
}

const ROOT = "/api/rag/debug"

export function listRagDebugCompanionTraces(limit = 20): Promise<RagDebugCompanionTrace[]> {
  return apiGet(`${ROOT}/companion-traces?limit=${Math.max(1, Math.min(limit, 100))}`)
}

export function listRagDebugConfigs(): Promise<RagDebugConfigProfile[]> {
  return apiGet(`${ROOT}/configs`)
}

export function createRagDebugConfig(payload: { name: string; description?: string; config: RagConfig; activate?: boolean }): Promise<RagDebugConfigProfile> {
  return apiPost(`${ROOT}/configs`, payload)
}

export function updateRagDebugConfig(configId: string, payload: Partial<{ name: string; description: string; config: RagConfig; activate: boolean }>): Promise<RagDebugConfigProfile> {
  return apiPatch(`${ROOT}/configs/${encodeURIComponent(configId)}`, payload)
}

export function activateRagDebugConfig(configId: string): Promise<RagDebugConfigProfile> {
  return apiPost(`${ROOT}/configs/${encodeURIComponent(configId)}/activate`, {})
}

export function clearRagDebugConfigReindex(configId: string): Promise<RagDebugConfigProfile> {
  return apiPost(`${ROOT}/configs/${encodeURIComponent(configId)}/clear-reindex`, {})
}

export function deleteRagDebugConfig(configId: string): Promise<{ config_id: string; deleted: boolean }> {
  return apiDelete(`${ROOT}/configs/${encodeURIComponent(configId)}`)
}

export function listRagDebugDocuments(): Promise<RagDebugDocument[]> {
  return apiGet(`${ROOT}/documents`)
}

export function listRagDebugChunks(params: { documentId?: string; query?: string; page?: number; pageSize?: number } = {}): Promise<RagDebugChunkPage> {
  const search = new URLSearchParams()
  if (params.documentId) search.set("document_id", params.documentId)
  if (params.query) search.set("query", params.query)
  if (params.page) search.set("page", String(params.page))
  if (params.pageSize) search.set("page_size", String(params.pageSize))
  const query = search.size ? `?${search.toString()}` : ""
  return apiGet(`${ROOT}/chunks${query}`)
}

export function getRagDebugChunk(chunkId: string): Promise<RagDebugChunk> {
  return apiGet(`${ROOT}/chunks/${encodeURIComponent(chunkId)}`)
}

export function startRagDebugRun(payload: { query: string; config_id: string; document_ids?: string[]; top_k: number; include_answer: boolean; knowledge_access_policy?: "auto" | "always" | "never" }): Promise<RagDebugRunAccepted> {
  return apiPost(`${ROOT}/runs`, payload)
}

export function getRagDebugRun(runId: string): Promise<RagDebugTraceResponse> {
  return apiGet(`${ROOT}/runs/${encodeURIComponent(runId)}`)
}

export function getRagDebugRunEvents(runId: string, after = -1): Promise<{ run_id: string; trace_id: string; status: RagDebugRunStatus; events: RagDebugStageEvent[] }> {
  return apiGet(`${ROOT}/runs/${encodeURIComponent(runId)}/events?after=${after}`)
}

export function cancelRagDebugRun(runId: string): Promise<RagDebugTraceResponse> {
  return apiPost(`${ROOT}/runs/${encodeURIComponent(runId)}/cancel`, {})
}

export function ragDebugRunWebSocketUrl(runId: string): string {
  return apiWebSocketUrl(`${ROOT}/runs/${encodeURIComponent(runId)}/stream`)
}

export function listRagDebugDatasets(): Promise<RagDebugDataset[]> {
  return apiGet(`${ROOT}/datasets`)
}

export function createRagDebugDataset(payload: { name: string; description?: string }): Promise<RagDebugDataset> {
  return apiPost(`${ROOT}/datasets`, payload)
}

export function deleteRagDebugDataset(datasetId: string): Promise<{ dataset_id: string; deleted: boolean }> {
  return apiDelete(`${ROOT}/datasets/${encodeURIComponent(datasetId)}`)
}

export function listRagDebugCases(datasetId: string): Promise<RagDebugCase[]> {
  return apiGet(`${ROOT}/datasets/${encodeURIComponent(datasetId)}/cases`)
}

export function saveRagDebugCase(datasetId: string, payload: RagDebugCase): Promise<RagDebugCase> {
  return apiPost(`${ROOT}/datasets/${encodeURIComponent(datasetId)}/cases`, payload)
}

export function updateRagDebugCase(datasetId: string, caseId: string, payload: RagDebugCase): Promise<RagDebugCase> {
  return apiPatch(`${ROOT}/datasets/${encodeURIComponent(datasetId)}/cases/${encodeURIComponent(caseId)}`, payload)
}

export function deleteRagDebugCase(datasetId: string, caseId: string): Promise<{ dataset_id: string; case_id: string; deleted: boolean }> {
  return apiDelete(`${ROOT}/datasets/${encodeURIComponent(datasetId)}/cases/${encodeURIComponent(caseId)}`)
}

export function importRagDebugDataset(payload: { name: string; description?: string; content: string; format?: "json" | "jsonl" }): Promise<RagDebugDataset> {
  return apiPost(`${ROOT}/datasets/import`, payload)
}

export function exportRagDebugDataset(datasetId: string, format: "json" | "jsonl" = "json"): Promise<{ dataset: RagDebugDataset; format: "json" | "jsonl"; content: string }> {
  return apiGet(`${ROOT}/datasets/${encodeURIComponent(datasetId)}/export?format=${format}`)
}

export function evaluateRagDebugDataset(payload: { dataset_id: string; config_id: string; top_k: number; case_ids?: string[] }): Promise<RagDebugEvaluationResponse> {
  return apiPost(`${ROOT}/evaluation`, payload)
}

export function compareRagDebugDataset(payload: { dataset_id: string; baseline_config_id: string; candidate_config_id: string; top_k: number; case_ids?: string[] }): Promise<RagDebugCompareResponse> {
  return apiPost(`${ROOT}/compare`, payload)
}
