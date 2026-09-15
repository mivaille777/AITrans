export interface AgentEvidenceItem {
  evidence_id: string
  source_type: string
  source_id: string
  title: string
  resource_url: string
  location: string
  excerpt: string
  score: number | null
  metadata: Record<string, unknown>
}

export interface AgentCitationRef {
  citation_id: string
  evidence_ids: string[]
  label: string
}
