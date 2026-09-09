import type { KnowledgeAction } from "./KnowledgeActionMenu"
import type { KnowledgeItem } from "./knowledge-types"

export type KnowledgeActionContext = {
  item: KnowledgeItem
}

/**
 * Central entry point for Knowledge Card AI operations.
 *
 * The dispatcher intentionally contains no model calls yet. It provides a
 * stable boundary between UI actions and future Agent Runtime execution.
 */
export function dispatchKnowledgeAction(
  action: KnowledgeAction,
  context: KnowledgeActionContext,
) {
  switch (action) {
    case "summarize":
      return {
        type: "KNOWLEDGE_SUMMARIZE_REQUEST",
        item: context.item,
      }
    case "explain":
      return {
        type: "KNOWLEDGE_EXPLAIN_REQUEST",
        item: context.item,
      }
    case "translate":
      return {
        type: "KNOWLEDGE_TRANSLATE_REQUEST",
        item: context.item,
      }
    case "generate_notes":
      return {
        type: "KNOWLEDGE_NOTE_GENERATION_REQUEST",
        item: context.item,
      }
    case "ask_agent":
      return {
        type: "KNOWLEDGE_AGENT_QUERY_REQUEST",
        item: context.item,
      }
    default:
      return null
  }
}
