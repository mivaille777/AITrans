import type { AgentKnowledgeContext, AgentRunRequest, AgentWorkflowAction } from "../../../api/agent"
import type { ReadingContextFields } from "../../../api/types"
import type { AgentContextMode } from "./agent-context-mode"

export interface BuildAgentRunRequestInput {
  context: ReadingContextFields
  contextMode?: AgentContextMode
  sessionId: string
  traceId: string
  requestId: number
  userMessage: string
  sourceText: string
  translatedText: string
  sourceLanguage: string
  targetLanguage: string
  conversationId: string
  workspaceId?: string
  confirmedWriteTools?: string[]
  knowledgeDocumentIds?: string[]
  researchSourceIds?: string[]
  knowledgeContext?: AgentKnowledgeContext | null
  temporary?: boolean
  workflowAction?: AgentWorkflowAction
}

export function buildAgentRunRequest({
  context,
  contextMode = "general",
  sessionId,
  traceId,
  requestId,
  userMessage,
  sourceText,
  translatedText,
  sourceLanguage,
  targetLanguage,
  conversationId,
  workspaceId = "",
  confirmedWriteTools = [],
  knowledgeDocumentIds = [],
  researchSourceIds = [],
  knowledgeContext = null,
  temporary = false,
  workflowAction = "",
}: BuildAgentRunRequestInput): AgentRunRequest {
  return {
    ...context,
    session_id: sessionId,
    client_id: sessionId,
    client_surface: "main",
    context_mode: contextMode,
    trace_id: traceId,
    user_message: userMessage,
    source_text: sourceText,
    translated_text: translatedText,
    source_language: sourceLanguage,
    target_language: targetLanguage,
    style: "academic",
    conversation_id: conversationId,
    workspace_id: workspaceId,
    confirmed_write_tools: confirmedWriteTools,
    knowledge_document_ids: knowledgeDocumentIds,
    research_source_ids: researchSourceIds,
    knowledge_context: knowledgeContext,
    request_id: requestId,
    temporary,
    workflow_action: workflowAction,
  }
}
