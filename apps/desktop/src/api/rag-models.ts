import { apiDelete, apiGet, apiPost } from "./client"

export type RagModelId = "qwen3-embedding-0.6b" | "qwen3-reranker-0.6b"
export type RagModelState = "not_installed" | "downloading" | "installed" | "invalid"
export type RagModelSource = "none" | "managed" | "huggingface_cache"

export interface RagModelStatus {
  model_id: RagModelId
  display_name: string
  repository_id: string
  state: RagModelState
  installed: boolean
  verified: boolean
  source: RagModelSource
  removable: boolean
  path: string
  disk_usage_bytes: number
  runtime_ready?: boolean
  runtime_error?: string
  error: string
}

export interface RagModelListResponse {
  models_root: string
  models: RagModelStatus[]
}

export interface RagModelOperationResponse {
  model: RagModelStatus
  changed: boolean
}

const MODELS_PATH = "/api/rag/models"

export function listRagModels(): Promise<RagModelListResponse> {
  return apiGet(MODELS_PATH)
}

export function getRagModel(modelId: RagModelId): Promise<RagModelStatus> {
  return apiGet(`${MODELS_PATH}/${encodeURIComponent(modelId)}`)
}

export function downloadRagModel(modelId: RagModelId): Promise<RagModelOperationResponse> {
  return apiPost(`${MODELS_PATH}/${encodeURIComponent(modelId)}/download`, {})
}

export function verifyRagModel(modelId: RagModelId): Promise<RagModelStatus> {
  return apiPost(`${MODELS_PATH}/${encodeURIComponent(modelId)}/verify`, {})
}

export function removeRagModel(modelId: RagModelId): Promise<RagModelOperationResponse> {
  return apiDelete(`${MODELS_PATH}/${encodeURIComponent(modelId)}`)
}
