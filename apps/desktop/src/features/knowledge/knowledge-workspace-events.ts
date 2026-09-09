import type { KnowledgeItem } from "./knowledge-types"

export type KnowledgeWorkspaceEventType =
  | "KNOWLEDGE_SUMMARIZE_REQUEST"
  | "KNOWLEDGE_EXPLAIN_REQUEST"
  | "KNOWLEDGE_TRANSLATE_REQUEST"
  | "KNOWLEDGE_NOTE_GENERATION_REQUEST"
  | "KNOWLEDGE_AGENT_QUERY_REQUEST"

export type KnowledgeWorkspaceEvent = {
  type: KnowledgeWorkspaceEventType
  item: KnowledgeItem
}

/**
 * Workspace boundary for future Agent Runtime integration.
 * UI components should emit workspace events instead of calling agents directly.
 */
export function emitKnowledgeWorkspaceEvent(
  event: KnowledgeWorkspaceEvent,
) {
  return event
}
