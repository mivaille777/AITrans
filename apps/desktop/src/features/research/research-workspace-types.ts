export type ResearchWorkspaceMemberKind = "document" | "note" | "conversation"

export interface ResearchProjectWorkspaceSummary {
  workspace_id: string
  name: string
  description: string
  research_goal: string
  created_at: string
  updated_at: string
  document_count: number
  note_count: number
  conversation_count: number
}

export interface ResearchProjectWorkspaceProfile extends ResearchProjectWorkspaceSummary {
  document_ids: string[]
  note_ids: string[]
  conversation_ids: string[]
}

export interface ResearchProjectWorkspaceListResponse {
  total: number
  workspaces: ResearchProjectWorkspaceSummary[]
}

export interface ResearchProjectWorkspaceCreateRequest {
  name: string
  description?: string
  research_goal?: string
}

export interface ResearchProjectWorkspaceDeleteResponse {
  deleted: boolean
  workspace_id: string
  resources_preserved: boolean
}

export interface ResearchProjectWorkspaceMemberResponse {
  workspace_id: string
  kind: ResearchWorkspaceMemberKind
  resource_id: string
  attached: boolean
}
