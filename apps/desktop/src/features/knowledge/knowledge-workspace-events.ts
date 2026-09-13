import type { KnowledgeItem, KnowledgeUserItemType } from "./knowledge-types"

export type KnowledgeWorkspaceEventType =
  | "KNOWLEDGE_SUMMARIZE_REQUEST"
  | "KNOWLEDGE_EXPLAIN_REQUEST"
  | "KNOWLEDGE_TRANSLATE_REQUEST"
  | "KNOWLEDGE_NOTE_GENERATION_REQUEST"
  | "KNOWLEDGE_AGENT_QUERY_REQUEST"

export type KnowledgeWritebackIntent = {
  itemType: KnowledgeUserItemType
  operation: string
  relationType: string
}

export type KnowledgeAgentRequest = {
  prompt: string
  autoSubmit: boolean
  writeback: KnowledgeWritebackIntent | null
}

export type KnowledgeWorkspaceEvent = {
  type: KnowledgeWorkspaceEventType
  item: KnowledgeItem
  agentRequest: KnowledgeAgentRequest
}

/**
 * Workspace boundary for Agent Runtime integration.
 * UI components emit a semantic workspace event rather than calling a model
 * or mutating canonical Knowledge storage directly.
 */
export function emitKnowledgeWorkspaceEvent(
  event: KnowledgeWorkspaceEvent,
) {
  return event
}
