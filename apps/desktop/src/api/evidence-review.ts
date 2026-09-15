import { apiGet, apiPatch, apiPost } from "./client"
import type {
  AgentLiteratureSynthesisResponse,
  EvidenceReviewSnapshot,
  EvidenceReviewStatus,
  LiteratureSynthesisPlan,
  ReviewedEvidenceItem,
} from "../features/research/evidence-review-types"

export function getEvidenceReview(
  workspaceId: string,
  query = "",
  limit = 100,
): Promise<EvidenceReviewSnapshot> {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  return apiGet<EvidenceReviewSnapshot>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}/evidence-review?${params.toString()}`,
  )
}

export function updateEvidenceReview(
  workspaceId: string,
  entryId: string,
  status: EvidenceReviewStatus,
  note = "",
): Promise<ReviewedEvidenceItem> {
  return apiPatch<ReviewedEvidenceItem, { status: EvidenceReviewStatus; note: string }>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}/evidence-review/${encodeURIComponent(entryId)}`,
    { status, note },
  )
}

export function synthesizeLiterature(
  workspaceId: string,
  query = "",
): Promise<LiteratureSynthesisPlan> {
  return apiPost<LiteratureSynthesisPlan, { query: string }>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}/literature-synthesis`,
    { query },
  )
}

export function synthesizeLiteratureWithAgent(
  workspaceId: string,
  query = "",
): Promise<AgentLiteratureSynthesisResponse> {
  return apiPost<AgentLiteratureSynthesisResponse, { query: string }>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}/literature-synthesis/agent`,
    { query },
  )
}
