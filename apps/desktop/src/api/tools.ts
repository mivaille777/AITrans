import { apiGet, apiPatch } from "./client"

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
