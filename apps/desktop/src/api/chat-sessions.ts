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
    Pick<ChatSessionConfiguration, "execution_mode" | "filesystem_workspace_id">
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
