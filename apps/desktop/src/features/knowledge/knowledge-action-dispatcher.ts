import type { KnowledgeAction } from "./KnowledgeActionMenu"
import type { KnowledgeItem } from "./knowledge-types"
import type { KnowledgeWorkspaceEvent } from "./knowledge-workspace-events"

export type KnowledgeActionContext = {
  item: KnowledgeItem
}

/**
 * Central entry point for Knowledge Card AI operations.
 *
 * The dispatcher stays model-free. It declares the Agent request and the
 * canonical write-back intent, while execution and confirmation remain owned
 * by Agent Runtime.
 */
export function dispatchKnowledgeAction(
  action: KnowledgeAction,
  context: KnowledgeActionContext,
): KnowledgeWorkspaceEvent | null {
  switch (action) {
    case "summarize":
      return {
        type: "KNOWLEDGE_SUMMARIZE_REQUEST",
        item: context.item,
        agentRequest: {
          prompt: "summarize the selection",
          autoSubmit: true,
          writeback: {
            itemType: "insight",
            operation: "summarize",
            relationType: "derived_from",
          },
        },
      }
    case "explain":
      return {
        type: "KNOWLEDGE_EXPLAIN_REQUEST",
        item: context.item,
        agentRequest: {
          prompt: "explain the selection",
          autoSubmit: true,
          writeback: {
            itemType: "insight",
            operation: "explain",
            relationType: "derived_from",
          },
        },
      }
    case "translate":
      return {
        type: "KNOWLEDGE_TRANSLATE_REQUEST",
        item: context.item,
        agentRequest: {
          prompt: "translate the selection",
          autoSubmit: true,
          writeback: {
            itemType: "note",
            operation: "translate",
            relationType: "derived_from",
          },
        },
      }
    case "generate_notes":
      return {
        type: "KNOWLEDGE_NOTE_GENERATION_REQUEST",
        item: context.item,
        agentRequest: {
          prompt: "summarize the selection",
          autoSubmit: true,
          writeback: {
            itemType: "note",
            operation: "generate_notes",
            relationType: "derived_from",
          },
        },
      }
    case "ask_agent":
      return {
        type: "KNOWLEDGE_AGENT_QUERY_REQUEST",
        item: context.item,
        agentRequest: {
          prompt: "",
          autoSubmit: false,
          writeback: {
            itemType: "insight",
            operation: "question",
            relationType: "derived_from",
          },
        },
      }
    default:
      return null
  }
}
