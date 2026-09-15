import type { AgentCitationRef, AgentEvidenceItem } from "../features/evidence/evidence-types"

export interface HealthResponse {
  status: "ok"
  service: string
}

export interface TranslationRequest {
  source_text: string
  source_language: string
  target_language: string
  request_id?: number
}

export interface TranslationResponse {
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  provider: string
  request_id: number
}

export interface TranslationStatusResponse {
  provider: string
  source_language: string
  target_language: string
}

export interface BrowserBridgeStatusResponse {
  running: boolean
  host: string
  port: number
  endpoint: string
  has_extension_activity: boolean
  last_activity_age_seconds: number | null
  last_title: string
  last_url: string
  last_heading: string
}

export interface BrowserSelection {
  selection_id: string
  text: string
  url: string
  title: string
  heading: string
  context_before: string
  context_after: string
  frame_url: string
  top_level: boolean
  captured_at_ms: number | null
}

export interface BrowserSelectionEnvelope {
  selection: BrowserSelection | null
}

export interface BrowserPage {
  page_id: string
  url: string
  title: string
  heading: string
  frame_url: string
}

export interface BrowserPageEnvelope {
  page: BrowserPage | null
}

export interface ReadingContextFields {
  resource_url: string
  resource_title: string
  /** Local UI/source identity only. It is not part of the LLM prompt-safe reading context. */
  application?: string
  section_heading: string
  context_before: string
  context_after: string
  source_kind: string
}

export type OverlayMode = "assistant" | "translation"
export type OverlayPhase = "hidden" | "idle" | "loading" | "ready" | "error"

export interface OverlayStateResponse extends ReadingContextFields {
  revision: number
  visible: boolean
  mode?: OverlayMode
  phase: OverlayPhase
  context_id: string
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  provider: string
  message: string
  translation_notice?: string
  companion_conversation_id?: string
}

export interface OverlayLoadingRequest extends Partial<ReadingContextFields> {
  context_id: string
  source_text: string
  source_language: string
  target_language: string
}

export interface OverlayPresentRequest extends OverlayLoadingRequest {
  translated_text: string
  provider: string
}

export interface OverlayErrorRequest extends Partial<ReadingContextFields> {
  context_id: string
  source_text: string
  source_language: string
  target_language: string
  message: string
}

export type QuickActionKey =
  | "ai_polish"
  | "reading_context_translate"
  | "reading_explain"
  | "reading_summarize"
  | "reading_section_role"
  | "reading_define_terms"
  | "reading_analyze_equation"
  | "reading_section_summarize"

export interface QuickActionRequest extends ReadingContextFields {
  action: QuickActionKey
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  style?: string
  request_id?: number
}

export interface QuickActionResponse {
  action: QuickActionKey
  output_text: string
  provider: string
  model: string
  request_id: number
}

export interface QuickActionStatusResponse {
  available: boolean
  provider: string
  model: string
  detail: string
}

export interface ResearchNoteSaveRequest extends ReadingContextFields {
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  ai_content?: string
  ai_action?: string
  user_note?: string
  conversation_id?: string
}

export interface ResearchNoteSaveResponse {
  note_id: string
  created: boolean
  display_title: string
  excerpt: string
  updated_at: string
  conversation_id: string
}

export interface ResearchNoteListItem {
  note_id: string
  display_title: string
  excerpt: string
  updated_at: string
  resource_url: string
  resource_title: string
  section_heading: string
  source_text: string
  translated_text: string
  context_before: string
  context_after: string
  source_kind: string
  ai_content: string
  ai_action: string
  conversation_id: string
}

export interface ResearchNoteListResponse {
  total: number
  notes: ResearchNoteListItem[]
}

export type ResearchSourceFamily = "browser" | "pdf" | "word" | "desktop" | "other"
export type ResearchIdentityQuality = "locator" | "title" | "note"

export interface ResearchSourceSummary {
  source_id: string
  display_title: string
  resource_url: string
  resource_locator: string
  source_kind: string
  source_family: ResearchSourceFamily
  identity_quality: ResearchIdentityQuality
  note_count: number
  section_count: number
  linked_conversation_count: number
  annotation_count: number
  ai_evidence_count: number
  updated_at: string
}

export interface ResearchSourceSection {
  section_id: string
  heading: string
  note_count: number
  linked_conversation_count: number
  annotation_count: number
  ai_evidence_count: number
  updated_at: string
}

export interface ResearchSourceProfile extends ResearchSourceSummary {
  sections: ResearchSourceSection[]
}

export interface ResearchNoteDetail extends ResearchNoteListItem {
  source_id: string
  created_at: string
  user_note: string
}

export interface ResearchWorkspaceResponse {
  total: number
  sources: ResearchSourceSummary[]
  notes: ResearchNoteDetail[]
}

export interface ResearchNoteDeleteResponse {
  deleted: boolean
  note_id: string
}

export interface CompanionHandoffRequest extends ReadingContextFields {
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  conversation_id?: string
  ai_content?: string
  ai_action?: string
  suggested_prompt?: string
}

export interface CompanionHandoff extends CompanionHandoffRequest {
  revision: number
  handoff_id: string
  created_at: string
  conversation_id: string
  ai_content: string
  ai_action: string
  suggested_prompt: string
}

export interface CompanionHandoffEnvelope {
  handoff: CompanionHandoff | null
}

export type CompanionChatRole = "user" | "assistant"
export type ChatContextMode = "general" | "reading"

export interface CompanionChatMessage {
  role: CompanionChatRole
  content: string
}

export interface CompanionChatRequest extends ReadingContextFields {
  conversation_id?: string
  session_id: string
  user_message: string
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  context_mode: ChatContextMode
  history: CompanionChatMessage[]
  request_id?: number
  knowledge_enabled: boolean
  knowledge_document_ids: string[]
}

export interface CompanionChatResponse {
  conversation_id: string
  session_id: string
  user_message: string
  output_text: string
  provider: string
  model: string
  request_id: number
  knowledge_enabled: boolean
  knowledge_fallback_reason: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
}

export interface CompanionChatStatusResponse {
  available: boolean
  provider: string
  model: string
  detail: string
}

export interface CompanionChatStreamAccepted {
  type: "accepted"
  request_id: number
  conversation_id: string
  message_id: string
  user_message_id?: string
}

export interface CompanionChatStreamDelta {
  type: "delta"
  request_id: number
  conversation_id: string
  message_id: string
  delta: string
  accumulated_text: string
}

export interface CompanionChatStreamDone {
  type: "done"
  request_id: number
  conversation_id: string
  message_id: string
  output_text: string
  provider: string
  model: string
  knowledge_enabled: boolean
  knowledge_fallback_reason: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
}

export interface CompanionChatStreamError {
  type: "error"
  request_id: number
  conversation_id: string
  message_id: string
  code: string
  message: string
}

export interface CompanionChatStreamCancelled {
  type: "cancelled"
  request_id: number
  conversation_id: string
  message_id: string
}

export type CompanionChatStreamEvent =
  | CompanionChatStreamAccepted
  | CompanionChatStreamDelta
  | CompanionChatStreamDone
  | CompanionChatStreamError
  | CompanionChatStreamCancelled

export type ConversationMessageStatus = "complete" | "streaming" | "cancelled" | "error"

export interface ConversationMessage {
  message_id: string
  conversation_id: string
  request_id: number
  role: CompanionChatRole
  content: string
  status: ConversationMessageStatus
  provider: string
  model: string
  error_code: string
  created_at: string
  updated_at: string
}

export interface ConversationSummary {
  conversation_id: string
  session_id: string
  title: string
  created_at: string
  updated_at: string
  provider: string
  model: string
  context_mode: ChatContextMode
  resource_title: string
  section_heading: string
  source_kind: string
}

export interface ConversationDetail extends ConversationSummary, ReadingContextFields {
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  messages: ConversationMessage[]
}

export interface ConversationListResponse {
  conversations: ConversationSummary[]
}

export interface ConversationContextUpdate {
  context_mode: ChatContextMode
  source_text?: string
  translated_text?: string
  source_language?: string
  target_language?: string
  resource_url?: string
  resource_title?: string
  application?: string
  section_heading?: string
  context_before?: string
  context_after?: string
  source_kind?: string
}

export interface ConversationDeleteResponse {
  deleted: boolean
  conversation_id: string
}
