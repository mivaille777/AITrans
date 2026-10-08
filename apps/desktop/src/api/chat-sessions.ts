import { apiDelete, apiGet, apiPatch, apiPost } from "./client"

export type ChatExecutionMode = "react" | "plan_execute"
export interface ChatAttachment {
  attachment_id: string
  name: string
  relative_path: string
  size_bytes: number
  text_chars: number
}
export interface ChatSessionConfiguration {
  session_id: string
  filesystem_workspace_id: string
  execution_mode: ChatExecutionMode
  filesystem_access?: "read_only" | "read_write"
  attachments: ChatAttachment[]
  pending_run_id: string
}
const path = (sessionId: string) =>
  `/api/companion/sessions/${encodeURIComponent(sessionId)}`
export const getChatConfiguration = (sessionId: string) =>
  apiGet<ChatSessionConfiguration>(path(sessionId))
export const updateChatConfiguration = (
  sessionId: string,
  update: Partial<
    Pick<ChatSessionConfiguration, "execution_mode" | "filesystem_workspace_id" | "filesystem_access">
  >,
) => apiPatch<ChatSessionConfiguration, typeof update>(path(sessionId), update)
export const importChatFile = (sessionId: string, filePath: string) =>
  apiPost<ChatSessionConfiguration, { path: string }>(
    `${path(sessionId)}/files`,
    { path: filePath },
  )
export const detachChatFile = (sessionId: string, attachmentId: string) =>
  apiDelete<ChatSessionConfiguration>(
    `${path(sessionId)}/files/${encodeURIComponent(attachmentId)}`,
  )

export interface WorkspaceFileEntry {
  relative_path: string
  name: string
  kind: "file" | "directory"
  size_bytes: number
}
export interface WorkspaceFileListing {
  display_path: string
  directory: string
  entries: WorkspaceFileEntry[]
  total: number
  next_offset: number
  has_more: boolean
  filesystem_access: "read_only" | "read_write"
}
export interface WorkspaceTextPreview {
  relative_path: string
  text: string
  sha256: string
  size_bytes: number
  encoding: string
  next_line: number
  has_more: boolean
}
export interface WorkspaceFileChange {
  change_id: string
  relative_path: string
  operation: string
  kind: "file" | "directory"
  size_bytes: number
  exists: boolean
  sha256: string
  created_at: string
  undone_by?: string
}
export interface WorkspaceUndoPreview {
  relative_path: string
  diff: string
  diff_truncated: boolean
  size_before: number
  size_after: number
  approval_token: string
}
export const browseChatWorkspace = (sessionId: string, directory = "", offset = 0) =>
  apiGet<WorkspaceFileListing>(`${path(sessionId)}/workspace?${new URLSearchParams({directory, offset: String(offset)})}`)
    .then(data => {if (!Array.isArray(data.entries)) throw new Error("文件浏览服务未就绪，请重启后端。"); return data})
export const previewChatWorkspaceText = (sessionId: string, relativePath: string, startLine = 1) =>
  apiGet<WorkspaceTextPreview>(`${path(sessionId)}/workspace/text?${new URLSearchParams({relative_path: relativePath, start_line: String(startLine)})}`)
export const getChatWorkspaceChanges = (sessionId: string) =>
  apiGet<WorkspaceFileChange[]>(`${path(sessionId)}/workspace/changes`)
    .then(data => {if (!Array.isArray(data)) throw new Error("文件变更服务未就绪，请重启后端。"); return data})
export const getChatWorkspaceLocation = (sessionId: string, relativePath: string) =>
  apiGet<{resource_url: string; kind: "file" | "directory"}>(`${path(sessionId)}/workspace/location?${new URLSearchParams({relative_path: relativePath})}`)
export const previewChatWorkspaceUndo = (sessionId: string, changeId: string) =>
  apiPost<WorkspaceUndoPreview, {change_id: string}>(`${path(sessionId)}/workspace/undo/preview`, {change_id: changeId})
export const applyChatWorkspaceUndo = (sessionId: string, token: string) =>
  apiPost<WorkspaceFileChange, {approval_token: string}>(`${path(sessionId)}/workspace/undo/apply`, {approval_token: token})
