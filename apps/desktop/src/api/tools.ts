import { apiGet, apiPatch, apiPost } from "./client"

export interface ToolSummary {
  tool_id: string
  name: string
  title: string
  description: string
  category: string
  namespace: string
  origin: "builtin" | "custom"
  effect: "read" | "compute" | "write"
  enabled: boolean
  available: boolean
  effective_enabled: boolean
  unavailable_reason: string
  risk_level: string
  archived?: boolean
}
export interface JsonSchema {
  title?: string
  type?: string | string[]
  description?: string
  properties?: Record<string, JsonSchema>
  required?: string[]
  items?: JsonSchema
  $ref?: string
  $defs?: Record<string, JsonSchema>
  anyOf?: JsonSchema[]
  enum?: unknown[]
  default?: unknown
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  [key: string]: unknown
}
export interface ToolExample { id: string; title: string; description: string; arguments: Record<string, unknown> }
export interface ToolDetail extends ToolSummary {
  tool_version: string
  revision: string
  input_schema: JsonSchema
  output_schema: JsonSchema
  input_profiles: Record<string, JsonSchema>
  context_requirements: string[]
  permissions: Record<string, unknown>
  limits: Record<string, unknown>
  examples: ToolExample[]
  execution_capabilities: Record<string, boolean>
  editable_fields: string[]
  updated_at: string | null
  configuration?: Record<string, unknown>
}
export interface ToolCatalog {
  items: ToolSummary[]
  categories: Record<string, number>
  total: number
  enabled: number
  disabled: number
  matched_total: number
  next_cursor: string | null
  catalog_revision: string
}
export function getTools(filters: { q?: string; category?: string; status?: string; cursor?: string } = {}) {
  const query = new URLSearchParams({ limit: "200", ...filters })
  return apiGet<ToolCatalog>(`/api/tools?${query}`)
}
export const getTool = (id: string) => apiGet<ToolDetail>(`/api/tools/${encodeURIComponent(id)}`)
export const setToolEnabled = (tool: ToolDetail, enabled: boolean) => apiPatch<ToolDetail, { revision: string; enabled: boolean }>(`/api/tools/${encodeURIComponent(tool.tool_id)}`, { revision: tool.revision, enabled })

export interface ToolTestRequest {
  arguments: Record<string, unknown>
  context_selection: { research_workspace_id: string; filesystem_workspace_id: string; knowledge_document_ids: string[]; reading_context: Record<string, unknown> }
  timeout_seconds: number
  stream_output: boolean
  client_request_id: string
}
export interface ToolTestRun {
  test_run_id: string; tool_id: string; tool_name: string; trace_id: string; tool_call_id: string
  status: string; execution_state: string; created_at: string; updated_at: string; finished_at: string | null; elapsed_ms: number
  result: Record<string, unknown> | null; result_truncated: boolean; error: { code: string; message: string } | null
  approval_id: string | null; approval_summary: Record<string, unknown> | null
}
const testPath = (toolId: string, runId?: string) => `/api/tools/${encodeURIComponent(toolId)}/test-runs${runId ? `/${encodeURIComponent(runId)}` : ""}`
export const validateToolTest = (id: string, body: ToolTestRequest) => apiPost<{ valid: boolean }, ToolTestRequest>(`/api/tools/${encodeURIComponent(id)}/validate`, body)
export const createToolTest = (id: string, body: ToolTestRequest) => apiPost<ToolTestRun, ToolTestRequest>(testPath(id), body)
export const getToolTest = (id: string, run: string) => apiGet<ToolTestRun>(testPath(id, run))
export const cancelToolTest = (id: string, run: string) => apiPost<ToolTestRun, object>(testPath(id, run) + "/cancel", {})
export const approveToolTest = (id: string, run: string, approval: string) => apiPost<ToolTestRun, { approval_id: string }>(testPath(id, run) + "/approve", { approval_id: approval })
export interface ToolTestEvent { seq: number; type: string; test_run_id: string; status: string; execution_state: string; at: string; elapsed_ms: number; error_code: string | null }
export const getToolTestHistory = (id: string, cursor?: string) => apiGet<{ items: ToolTestRun[]; next_cursor: string | null }>(testPath(id) + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""))
export const getToolTestEvents = (id: string, run: string) => apiGet<{ items: ToolTestEvent[] }>(testPath(id, run) + "/event-log")
export const createCustomTool = (preset: Record<string, unknown>) => apiPost<ToolDetail, Record<string, unknown>>("/api/tools/custom", preset)
export const editToolConfiguration = (tool: ToolDetail, config: Record<string, unknown>) => apiPatch<ToolDetail, object>(`/api/tools/${encodeURIComponent(tool.tool_id)}`, { revision: tool.revision, [tool.origin === "custom" ? "preset" : "config"]: config })
export interface ToolImportPreview { preview_token: string; items: { name: string; template_id: string; enabled: boolean }[]; conflicts: { name: string; archived: boolean }[]; message: string }
export const previewToolImport = (document: Record<string, unknown>) => apiPost<ToolImportPreview, object>("/api/tools/imports/preview", document)
export const applyToolImport = (document: Record<string, unknown>, preview: ToolImportPreview, replace: boolean) => apiPost<{ items: ToolDetail[] }, object>("/api/tools/imports", { document, preview_token: preview.preview_token, conflict_mode: replace ? "replace" : "reject" })
export const archiveTool = (tool: ToolDetail) => apiPost<ToolDetail, object>(`/api/tools/${encodeURIComponent(tool.tool_id)}/archive`, { revision: tool.revision })
