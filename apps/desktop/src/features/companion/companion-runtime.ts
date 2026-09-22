import type { CompanionClientSurface } from "../../api/companion"
import type {
  AgentRunSnapshot,
  AgentTraceEvent,
  KnowledgeAccessDecision,
  KnowledgeAccessPolicy,
} from "../../api/agent"
import type {
  ChatContextMode,
  CompanionChatMessage,
  CompanionChatRequest,
  CompanionHandoff,
  ConversationDetail,
  ConversationMessage,
} from "../../api/types"
import type { AgentCitationRef, AgentEvidenceItem } from "../evidence/evidence-types"

export type CompanionMessageStatus = "complete" | "streaming" | "cancelled" | "error"
export type CompanionGenerationPhase =
  | "routing"
  | "retrieving"
  | "generating"
  | "verifying"
  | "complete"
export type CompanionTransport = "companion" | "agent"
export type CompanionAgentPhase =
  | "idle"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "confirmation_required"
  | "error"
export type CompanionInspectorView = "context" | "run"

export interface CompanionRuntimeMessage extends CompanionChatMessage {
  id: string
  status: CompanionMessageStatus
  provider?: string
  model?: string
  serverMessageId?: string
  errorCode?: string
  generationPhase?: CompanionGenerationPhase
  knowledgeAccessPolicy?: KnowledgeAccessPolicy
  knowledgeEnabled?: boolean
  knowledgeDecision?: KnowledgeAccessDecision | null
  knowledgeRetrieved?: boolean
  knowledgeDocumentCount?: number
  knowledgeChunkCount?: number
  knowledgeFallbackReason?: string
  evidence?: AgentEvidenceItem[]
  citations?: AgentCitationRef[]
}

export interface CompanionAgentRuntimeState {
  transport: CompanionTransport
  agentPhase: CompanionAgentPhase
  runId: string
  traceId: string
  agentEvents: AgentTraceEvent[]
  agentSnapshot: AgentRunSnapshot | null
  selectedTools: string[]
  inspectorView: CompanionInspectorView
}

export interface CompanionContextSnapshot {
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  resource_url: string
  resource_title: string
  application?: string
  section_heading: string
  context_before: string
  context_after: string
  source_kind: string
  ai_content?: string
  ai_action?: string
}

export const EMPTY_COMPANION_CONTEXT: CompanionContextSnapshot = {
  source_text: "",
  translated_text: "",
  source_language: "auto",
  target_language: "zh-CN",
  resource_url: "",
  resource_title: "",
  application: "",
  section_heading: "",
  context_before: "",
  context_after: "",
  source_kind: "",
}

export function companionContextSnapshot(
  context: CompanionHandoff | ConversationDetail,
): CompanionContextSnapshot {
  return {
    source_text: context.source_text,
    translated_text: context.translated_text,
    source_language: context.source_language,
    target_language: context.target_language,
    resource_url: context.resource_url,
    resource_title: context.resource_title,
    application: context.application ?? "",
    section_heading: context.section_heading,
    context_before: context.context_before,
    context_after: context.context_after,
    source_kind: context.source_kind,
    ...("ai_content" in context
      ? { ai_content: context.ai_content, ai_action: context.ai_action }
      : {}),
  }
}

type ScopedCompanionHandoff = CompanionHandoff & {
  knowledge_access_policy?: KnowledgeAccessPolicy
  knowledge_enabled?: boolean
  knowledge_document_ids?: string[]
}

function normalizedDocumentIds(values: string[] | undefined): string[] {
  return [...new Set((values ?? []).map((value) => value.trim()).filter(Boolean))].slice(0, 100)
}

export interface CompanionHandoffRuntimeSeed {
  context: CompanionContextSnapshot
  contextMode: "reading"
  draft: string
  sessionId: string
  scopeId: string
  knowledgeAccessPolicy: KnowledgeAccessPolicy
  knowledgeEnabled: boolean
  knowledgeDocumentIds: string[]
}

export function companionHandoffRuntimeSeed(
  handoff: CompanionHandoff,
): CompanionHandoffRuntimeSeed {
  const scoped = handoff as ScopedCompanionHandoff
  const knowledgeDocumentIds = normalizedDocumentIds(scoped.knowledge_document_ids)
  const knowledgeAccessPolicy = scoped.knowledge_access_policy
    ?? (scoped.knowledge_enabled ? "always" : "auto")
  return {
    context: companionContextSnapshot(handoff),
    contextMode: "reading",
    draft: handoff.suggested_prompt ?? "",
    sessionId: `companion-${handoff.handoff_id}`,
    scopeId: `handoff:${handoff.handoff_id}`,
    knowledgeAccessPolicy,
    knowledgeEnabled: knowledgeAccessPolicy === "always",
    knowledgeDocumentIds,
  }
}

export function companionHistory(
  messages: CompanionRuntimeMessage[],
  limit = 16,
): CompanionChatMessage[] {
  return messages
    .filter((message) => message.status === "complete" && message.content.trim())
    .slice(-Math.max(1, limit))
    .map(({ role, content }) => ({ role, content }))
}

type PersistedGroundingMessage = ConversationMessage & {
  knowledge_access_policy?: KnowledgeAccessPolicy
  knowledge_enabled?: boolean
  knowledge_decision?: KnowledgeAccessDecision | null
  knowledge_retrieved?: boolean
  knowledge_document_count?: number
  knowledge_chunk_count?: number
  knowledge_fallback_reason?: string
  evidence?: AgentEvidenceItem[]
  citations?: AgentCitationRef[]
}

export function restoreCompanionMessages(
  messages: ConversationMessage[],
): CompanionRuntimeMessage[] {
  return messages.map((message) => {
    const grounded = message as PersistedGroundingMessage
    return {
      id: message.message_id,
      role: message.role,
      content: message.content,
      status: message.status,
      provider: message.provider,
      model: message.model,
      serverMessageId: message.message_id,
      errorCode: message.error_code,
      generationPhase: message.status === "complete" ? "complete" : undefined,
      knowledgeAccessPolicy: grounded.knowledge_access_policy
        ?? (grounded.knowledge_enabled ? "always" : "auto"),
      knowledgeEnabled: grounded.knowledge_enabled ?? false,
      knowledgeDecision: grounded.knowledge_decision ?? null,
      knowledgeRetrieved: grounded.knowledge_retrieved,
      knowledgeDocumentCount: grounded.knowledge_document_count,
      knowledgeChunkCount: grounded.knowledge_chunk_count,
      knowledgeFallbackReason: grounded.knowledge_fallback_reason ?? "",
      evidence: grounded.evidence ?? [],
      citations: grounded.citations ?? [],
    }
  })
}

export function previousCompanionUserMessage(
  messages: CompanionRuntimeMessage[],
  assistantIndex: number,
): CompanionRuntimeMessage | null {
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "user") return messages[index]
  }
  return null
}

export function createCompanionScope(prefix: string): string {
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2, 10)}`
}

export interface CompanionChatRequestWithClient extends CompanionChatRequest {
  client_id: string
  client_surface: CompanionClientSurface
}

export interface CompanionRequestInput {
  conversationId?: string
  sessionId: string
  clientId?: string
  clientSurface?: CompanionClientSurface
  userMessage: string
  contextMode: ChatContextMode
  context?: CompanionContextSnapshot | null
  messages: CompanionRuntimeMessage[]
  requestId: number
  knowledgeAccessPolicy?: KnowledgeAccessPolicy
  knowledgeEnabled?: boolean
  knowledgeDocumentIds?: string[]
}

export function buildCompanionChatRequest({
  conversationId = "",
  sessionId,
  clientId = "",
  clientSurface = "main",
  userMessage,
  contextMode,
  context = EMPTY_COMPANION_CONTEXT,
  messages,
  requestId,
  knowledgeAccessPolicy,
  knowledgeEnabled,
  knowledgeDocumentIds = [],
}: CompanionRequestInput): CompanionChatRequestWithClient {
  const resolvedContext = context ?? EMPTY_COMPANION_CONTEXT
  const policy: KnowledgeAccessPolicy = knowledgeAccessPolicy
    ?? (knowledgeEnabled === undefined ? "auto" : knowledgeEnabled ? "always" : "never")
  return {
    conversation_id: conversationId,
    session_id: sessionId,
    client_id: clientId,
    client_surface: clientSurface === "unknown" ? "main" : clientSurface,
    user_message: userMessage.trim(),
    context_mode: contextMode,
    source_text: resolvedContext.source_text,
    translated_text: resolvedContext.translated_text,
    source_language: resolvedContext.source_language,
    target_language: resolvedContext.target_language,
    resource_url: resolvedContext.resource_url,
    resource_title: resolvedContext.resource_title,
    application: resolvedContext.application ?? "",
    section_heading: resolvedContext.section_heading,
    context_before: resolvedContext.context_before,
    context_after: resolvedContext.context_after,
    source_kind: resolvedContext.source_kind,
    history: companionHistory(messages),
    request_id: requestId,
    knowledge_access_policy: policy,
    // Keep the legacy field for older backends; policy is authoritative.
    knowledge_enabled: policy === "always",
    // Document IDs are an access boundary, not a retrieval command.
    knowledge_document_ids: knowledgeDocumentIds,
  }
}
