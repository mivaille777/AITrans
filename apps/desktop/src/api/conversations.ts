import { desktop } from "../desktop"
import { apiDelete, apiGet, apiPatch, apiPost } from "./client"
import type { MarkdownDocument } from "../shared/files/markdown-export"

export function exportConversationMarkdown(conversationId: string, messageId?: string): Promise<MarkdownDocument> {
  const query = messageId ? `?message_id=${encodeURIComponent(messageId)}` : ""
  return apiGet<MarkdownDocument>(`/api/conversations/${encodeURIComponent(conversationId)}/export/markdown${query}`)
}
import type {
  ConversationContextUpdate,
  ConversationDeleteResponse,
  ConversationDetail,
  ConversationListResponse,
} from "./types"

async function notifyConversationUpdated(conversationId: string): Promise<void> {
  const normalized = conversationId.trim()
  if (!normalized) return
  try {
    await desktop.overlay.notifyCompanionConversationChanged({
      conversationId: normalized,
      kind: "updated",
    })
  } catch {
    // Persisted conversation state remains authoritative if native delivery fails.
  }
}

async function notifyConversationDeleted(conversationId: string): Promise<void> {
  const normalized = conversationId.trim()
  if (!normalized) return
  try {
    await desktop.overlay.notifyCompanionConversationChanged({
      conversationId: normalized,
      kind: "deleted",
    })
  } catch {
    // The other window will discover deletion on its next explicit refresh.
  }
}

export function getConversations(limit = 30): Promise<ConversationListResponse> {
  return apiGet<ConversationListResponse>(`/api/conversations?limit=${limit}`)
}

export function getConversation(conversationId: string): Promise<ConversationDetail> {
  return apiGet<ConversationDetail>(`/api/conversations/${encodeURIComponent(conversationId)}`)
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<ConversationDetail> {
  const response = await apiPatch<ConversationDetail, { title: string }>(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
    { title },
  )
  await notifyConversationUpdated(response.conversation_id)
  return response
}

export async function rewindConversation(
  conversationId: string,
  userMessageId: string,
): Promise<ConversationDetail> {
  const response = await apiPost<ConversationDetail, { user_message_id: string }>(
    `/api/conversations/${encodeURIComponent(conversationId)}/rewind`,
    { user_message_id: userMessageId },
  )
  await notifyConversationUpdated(response.conversation_id)
  return response
}

export async function updateConversationContext(
  conversationId: string,
  payload: ConversationContextUpdate,
): Promise<ConversationDetail> {
  const response = await apiPatch<ConversationDetail, ConversationContextUpdate>(
    `/api/conversations/${encodeURIComponent(conversationId)}/context`,
    payload,
  )
  await notifyConversationUpdated(response.conversation_id)
  return response
}

export async function deleteConversation(
  conversationId: string,
): Promise<ConversationDeleteResponse> {
  const response = await apiDelete<ConversationDeleteResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
  )
  if (response.deleted) {
    await notifyConversationDeleted(response.conversation_id)
  }
  return response
}
