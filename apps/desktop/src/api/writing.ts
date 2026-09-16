import { apiGet, apiPost, apiPut } from "./client"

export interface ArtifactRef {
  artifact_id: string
  version: number
  kind: string
  content_hash: string
}

export interface ReferenceRecord {
  source_id: string
  title: string
  authors: string[]
  year: string
  doi: string
  evidence_ids: string[]
  missing_fields: string[]
}

export interface WritingParagraph {
  paragraph_id: string
  markdown: string
  content_hash: string
  evidence_ids: string[]
}

export interface WritingSectionSnapshot {
  section_id: string
  version: number
  title: string
  markdown: string
  paragraphs: WritingParagraph[]
  artifact_ref: ArtifactRef
  references: ReferenceRecord[]
  verification_status: string
  created_at: string
}

export interface WritingProjectSnapshot {
  project_id: string
  workspace_id: string
  title: string
  writing_goal: string
  outline_ref: ArtifactRef | null
  outline_version: number
  sections: WritingSectionSnapshot[]
  created_at: string
  updated_at: string
}

export interface WritingRevisionPreview {
  project_id: string
  section_id: string
  base_version: number
  revision_ref: ArtifactRef
  before: WritingParagraph[]
  after: WritingParagraph[]
}

export interface WritingOperationReceipt {
  operation_id: string
  project_id: string
  section_id: string
  result_version: number
  artifact_ref: ArtifactRef
  replayed: boolean
}

export interface WritingExport {
  project_id: string
  markdown: string
  references: ReferenceRecord[]
  outline_version: number
  section_versions: Record<string, number>
}

export function listWritingProjects(workspaceId: string): Promise<{ total: number; projects: WritingProjectSnapshot[] }> {
  return apiGet(`/api/writing/projects?workspace_id=${encodeURIComponent(workspaceId)}`)
}

export function createWritingProject(payload: {
  workspace_id: string
  title: string
  writing_goal: string
}): Promise<WritingProjectSnapshot> {
  return apiPost("/api/writing/projects", payload)
}

export function getWritingProject(projectId: string): Promise<WritingProjectSnapshot> {
  return apiGet(`/api/writing/projects/${encodeURIComponent(projectId)}`)
}

export function saveWritingArtifact(
  projectId: string,
  kind: "outline" | "sections",
  payload: { artifact_id: string; artifact_version: number; expected_version: number },
): Promise<WritingProjectSnapshot | WritingSectionSnapshot> {
  return apiPut(`/api/writing/projects/${encodeURIComponent(projectId)}/${kind}`, payload)
}

export function previewWritingRevision(
  projectId: string,
  sectionId: string,
  payload: {
    expected_version: number
    changes: Array<{
      paragraph_id: string
      replacement_markdown: string
      rationale: string
      evidence_ids: string[]
      category: "fact" | "interpretation" | "suggestion" | "user_supplied"
    }>
  },
): Promise<WritingRevisionPreview> {
  return apiPost(
    `/api/writing/projects/${encodeURIComponent(projectId)}/sections/${encodeURIComponent(sectionId)}/revision-preview`,
    payload,
  )
}

export function applyWritingRevision(
  projectId: string,
  payload: { artifact_id: string; artifact_version: number; expected_version: number; operation_id: string },
): Promise<WritingOperationReceipt> {
  return apiPost(`/api/writing/projects/${encodeURIComponent(projectId)}/revisions/apply`, payload)
}

export function exportWritingProject(projectId: string): Promise<WritingExport> {
  return apiGet(`/api/writing/projects/${encodeURIComponent(projectId)}/export`)
}
