import { apiDelete, apiGet, apiPatch, apiPost } from "./client"
import type {
  ResearchNoteDeleteResponse,
  ResearchNoteDetail,
  ResearchSourceProfile,
  ResearchWorkspaceResponse,
} from "./types"
import type {
  ResearchProjectWorkspaceCreateRequest,
  ResearchProjectWorkspaceDeleteResponse,
  ResearchProjectWorkspaceListResponse,
  ResearchProjectWorkspaceMemberResponse,
  ResearchProjectWorkspaceProfile,
  ResearchWorkspaceMemberKind,
} from "../features/research/research-workspace-types"

export function getResearchWorkspace(limit = 100): Promise<ResearchWorkspaceResponse> {
  return apiGet<ResearchWorkspaceResponse>(`/api/research/workspace?limit=${limit}`)
}

export function listResearchProjectWorkspaces(limit = 50): Promise<ResearchProjectWorkspaceListResponse> {
  return apiGet<ResearchProjectWorkspaceListResponse>(`/api/research/workspaces?limit=${limit}`)
}

export function createResearchProjectWorkspace(
  payload: ResearchProjectWorkspaceCreateRequest,
): Promise<ResearchProjectWorkspaceProfile> {
  return apiPost<ResearchProjectWorkspaceProfile, ResearchProjectWorkspaceCreateRequest>(
    "/api/research/workspaces",
    payload,
  )
}

export function getResearchProjectWorkspace(
  workspaceId: string,
): Promise<ResearchProjectWorkspaceProfile> {
  return apiGet<ResearchProjectWorkspaceProfile>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}`,
  )
}

export function updateResearchProjectWorkspace(
  workspaceId: string,
  payload: Required<ResearchProjectWorkspaceCreateRequest>,
): Promise<ResearchProjectWorkspaceProfile> {
  return apiPatch<ResearchProjectWorkspaceProfile, Required<ResearchProjectWorkspaceCreateRequest>>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}`,
    payload,
  )
}

export function deleteResearchProjectWorkspace(
  workspaceId: string,
): Promise<ResearchProjectWorkspaceDeleteResponse> {
  return apiDelete<ResearchProjectWorkspaceDeleteResponse>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}`,
  )
}

export function attachResearchProjectMember(
  workspaceId: string,
  kind: ResearchWorkspaceMemberKind,
  resourceId: string,
): Promise<ResearchProjectWorkspaceMemberResponse> {
  return apiPost<ResearchProjectWorkspaceMemberResponse, { resource_id: string }>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}/members/${kind}`,
    { resource_id: resourceId },
  )
}

export function detachResearchProjectMember(
  workspaceId: string,
  kind: ResearchWorkspaceMemberKind,
  resourceId: string,
): Promise<ResearchProjectWorkspaceMemberResponse> {
  return apiDelete<ResearchProjectWorkspaceMemberResponse>(
    `/api/research/workspaces/${encodeURIComponent(workspaceId)}/members/${kind}/${encodeURIComponent(resourceId)}`,
  )
}

export function getResearchSource(
  sourceId: string,
  limit = 100,
): Promise<ResearchSourceProfile> {
  return apiGet<ResearchSourceProfile>(
    `/api/research/sources/${encodeURIComponent(sourceId)}?limit=${limit}`,
  )
}

export function getResearchNote(noteId: string): Promise<ResearchNoteDetail> {
  return apiGet<ResearchNoteDetail>(`/api/research/notes/${encodeURIComponent(noteId)}`)
}

export function updateResearchNote(
  noteId: string,
  userNote: string,
): Promise<ResearchNoteDetail> {
  return apiPatch<ResearchNoteDetail, { user_note: string }>(
    `/api/research/notes/${encodeURIComponent(noteId)}`,
    { user_note: userNote },
  )
}

export function deleteResearchNote(noteId: string): Promise<ResearchNoteDeleteResponse> {
  return apiDelete<ResearchNoteDeleteResponse>(
    `/api/research/notes/${encodeURIComponent(noteId)}`,
  )
}
