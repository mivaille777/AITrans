export type EvidenceReviewStatus = "unreviewed" | "accepted" | "rejected" | "needs_review"
export type EvidenceMachineStatus = "supported" | "contested" | "insufficient" | "stale"
export type AgentLiteratureSynthesisStatus = "completed" | "fallback" | "no_evidence"

export interface EvidenceLedgerLink {
  evidence_id: string
  document_id: string
  role: "supporting" | "conflicting"
}

export interface ReviewedEvidenceItem {
  ledger: {
    entry: {
      entry_id: string
      statement: string
      links: EvidenceLedgerLink[]
    }
    validation: {
      status: EvidenceMachineStatus
      reason_codes: string[]
    }
  }
  review: {
    entry_id: string
    workspace_id: string
    status: EvidenceReviewStatus
    note: string
    reviewed_at: string
    updated_at: string
  }
}

export interface EvidenceReviewSnapshot {
  workspace_id: string
  query: string
  entry_count: number
  unreviewed_count: number
  accepted_count: number
  rejected_count: number
  needs_review_count: number
  items: ReviewedEvidenceItem[]
}

export interface LiteratureSynthesisItem {
  entry_id: string
  statement: string
  machine_status: EvidenceMachineStatus
  review_status: EvidenceReviewStatus
  bucket: "consensus" | "disagreement" | "excluded"
  reason: string
  document_ids: string[]
  evidence_ids: string[]
}

export interface LiteratureSynthesisPlan {
  workspace_id: string
  query: string
  included_count: number
  excluded_count: number
  consensus: LiteratureSynthesisItem[]
  disagreements: LiteratureSynthesisItem[]
  excluded: LiteratureSynthesisItem[]
  draft_markdown: string
}

export interface AgentLiteratureSynthesisVerification {
  passed: boolean
  claim_count: number
  cited_claim_count: number
  supported_claim_count: number
  unsupported_claim_count: number
  invalid_citation_count: number
  citation_coverage: number
  support_rate: number
  reason_codes: string[]
}

export interface AgentLiteratureSynthesisResponse {
  workspace_id: string
  query: string
  status: AgentLiteratureSynthesisStatus
  output_text: string
  provider: string
  model: string
  prompt_id: string
  included_count: number
  excluded_count: number
  evidence_count: number
  citation_count: number
  fallback_applied: boolean
  fallback_reason: string
  verification: AgentLiteratureSynthesisVerification | null
  plan: LiteratureSynthesisPlan
}
