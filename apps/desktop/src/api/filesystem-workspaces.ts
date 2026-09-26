import { apiDelete, apiGet, apiPost } from "./client"

export type FilesystemWorkspaceStatus = "active" | "missing" | "revoked"

export interface FilesystemWorkspace {
  workspace_id: string
  display_name: string
  display_path?: string
  readable: boolean
  writable: boolean
  status: FilesystemWorkspaceStatus
  created_at: string
  last_used_at: string
}

export function createFilesystemWorkspace(path: string): Promise<FilesystemWorkspace> {
  return apiPost<FilesystemWorkspace, { path: string }>(
    "/api/agent/filesystem-workspaces",
    { path },
  )
}

export function listFilesystemWorkspaces(): Promise<FilesystemWorkspace[]> {
  return apiGet<FilesystemWorkspace[]>("/api/agent/filesystem-workspaces")
}

export function getFilesystemWorkspace(workspaceId: string): Promise<FilesystemWorkspace> {
  return apiGet<FilesystemWorkspace>(
    `/api/agent/filesystem-workspaces/${encodeURIComponent(workspaceId)}`,
  )
}

export function revokeFilesystemWorkspace(workspaceId: string): Promise<{ workspace_id: string; revoked: boolean }> {
  return apiDelete<{ workspace_id: string; revoked: boolean }>(
    `/api/agent/filesystem-workspaces/${encodeURIComponent(workspaceId)}`,
  )
}
