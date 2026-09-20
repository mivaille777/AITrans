import { apiPost } from "./client"

export interface CuratorCommitResult {
  target_key: string
  target_kind: "note" | "item" | "relation_proposal"
  status: "committed" | "failed" | "skipped"
  object_id: string
  error_code: string
  message: string
}

export interface CuratorCommitReceipt {
  operation_id: string
  artifact_id: string
  artifact_version: number
  workspace_id: string
  status: "completed" | "partial" | "failed" | "in_progress"
  results: CuratorCommitResult[]
  replayed: boolean
}

export function commitCuratorDraft(payload: {
  artifact_id: string
  artifact_version: number
  operation_id: string
  scope: Record<string, unknown>
  selected_draft_ids: string[]
}): Promise<CuratorCommitReceipt> {
  return apiPost<CuratorCommitReceipt, typeof payload>("/api/curator/commit", payload)
}
