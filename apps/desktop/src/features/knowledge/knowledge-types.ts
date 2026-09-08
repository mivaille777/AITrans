export type KnowledgeDocumentStatus =
  | "pending"
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed"

export interface KnowledgeDocument {
  document_id: string
  title: string
  source_uri: string
  source_type: string
  status: KnowledgeDocumentStatus
  chunk_count: number
  indexed_at: string | null
  error: string
  content_hash: string
  parser_version: string
  chunker_version: string
  embedding_model: string
  embedding_dimension: number
  structure_quality?: string
  section_count?: number
  reindex_recommended?: boolean
}

export interface KnowledgeDocumentListResponse {
  total: number
  documents: KnowledgeDocument[]
}

export interface KnowledgeDocumentImportResponse {
  document: KnowledgeDocument
  reused_existing: boolean
  elapsed_ms: number
}

export interface KnowledgeDocumentDeleteResponse {
  document_id: string
  deleted: boolean
  source_file_preserved: boolean
}

export interface KnowledgeDocumentStatusResponse {
  document_id: string
  status: KnowledgeDocumentStatus
  chunk_count: number
  indexed_at: string | null
  error: string
}

export interface KnowledgeDocumentOutlineSection {
  section_id: string
  heading: string
  level: number
  parent_section_id: string | null
  section_path: string[]
  page_start: number | null
  page_end: number | null
  block_count: number
  has_equations: boolean
  has_tables: boolean
  has_figures: boolean
  reference_section: boolean
  synthetic: boolean
}

export interface KnowledgeDocumentOutline {
  document_id: string
  title: string
  page_count: number
  section_count: number
  sections: KnowledgeDocumentOutlineSection[]
}

export interface KnowledgeDocumentSection {
  document_id: string
  section_id: string
  heading: string
  level: number
  section_path: string[]
  page_start: number | null
  page_end: number | null
  text: string
  truncated: boolean
}

export interface KnowledgeRuntime {
  enabled: boolean
  embedding_provider: string
  embedding_model: string
  embedding_status: string
  device: string
  dimension: number
  vector_store_provider: string
  collection_name: string
  document_count: number
  ready_document_count: number
  indexed_chunk_count: number
  max_file_bytes: number
}

export type KnowledgeItemType = "paper" | "note" | "concept" | "highlight" | "document" | "web"

export interface KnowledgeItem {
  item_id: string
  item_type: KnowledgeItemType
  title: string
  summary: string
  resource_document_id: string | null
  source_uri: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface KnowledgeItemListResponse {
  total: number
  items: KnowledgeItem[]
}

export interface KnowledgeItemCreateInput {
  item_type: Exclude<KnowledgeItemType, "document" | "web">
  title: string
  summary?: string
  source_uri?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeItemUpdateInput {
  item_type?: KnowledgeItemType
  title?: string
  summary?: string
  source_uri?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeItemDeleteResponse {
  item_id: string
  deleted: boolean
}

export type KnowledgeRelationOrigin = "manual" | "imported" | "ai" | "citation" | "rag"

export interface KnowledgeRelation {
  relation_id: string
  source_item_id: string
  target_item_id: string
  relation_type: string
  label: string
  origin: KnowledgeRelationOrigin
  confidence: number | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface KnowledgeRelationListResponse {
  total: number
  relations: KnowledgeRelation[]
}

export interface KnowledgeRelationCreateInput {
  source_item_id: string
  target_item_id: string
  relation_type: string
  label?: string
  origin?: KnowledgeRelationOrigin
  confidence?: number | null
}

export interface KnowledgeRelationUpdateInput {
  relation_type?: string
  label?: string
  confidence?: number | null
}

export interface KnowledgeRelationDeleteResponse {
  relation_id: string
  deleted: boolean
}

export type KnowledgeRelationSuggestionStatus = "pending" | "accepted" | "rejected"

export interface KnowledgeRelationSuggestion {
  suggestion_id: string
  focus_item_id: string
  source_item_id: string
  target_item_id: string
  relation_type: string
  label: string
  rationale: string
  confidence: number
  evidence_item_ids: string[]
  status: KnowledgeRelationSuggestionStatus
  accepted_relation_id: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface KnowledgeRelationSuggestionGenerateInput {
  focus_item_id: string
  candidate_item_ids?: string[]
  max_suggestions?: number
}

export interface KnowledgeRelationSuggestionListResponse {
  total: number
  suggestions: KnowledgeRelationSuggestion[]
}

export interface KnowledgeRelationSuggestionDecisionResponse {
  suggestion: KnowledgeRelationSuggestion
  relation: KnowledgeRelation | null
}

export interface KnowledgeBoard {
  board_id: string
  name: string
  description: string
  created_at: string
  updated_at: string
}

export interface KnowledgeBoardNode {
  board_id: string
  item_id: string
  x: number
  y: number
  width: number
  height: number
  collapsed: boolean
  z_index: number
  created_at: string
  updated_at: string
}

export interface KnowledgeBoardListResponse {
  total: number
  boards: KnowledgeBoard[]
}

export interface KnowledgeBoardSnapshot {
  board: KnowledgeBoard
  nodes: KnowledgeBoardNode[]
}

export interface KnowledgeBoardCreateInput {
  name: string
  description?: string
}

export interface KnowledgeBoardNodeInput {
  x: number
  y: number
  width?: number
  height?: number
  collapsed?: boolean
  z_index?: number
}

export interface KnowledgeBoardNodeDeleteResponse {
  board_id: string
  item_id: string
  deleted: boolean
}

export interface KnowledgeBoardDeleteResponse {
  board_id: string
  deleted: boolean
}
