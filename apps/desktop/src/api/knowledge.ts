import { apiDelete, apiGet, apiPatch, apiPost } from "./client"
import type {
  KnowledgeDocument,
  KnowledgeDocumentDeleteResponse,
  KnowledgeDocumentImportResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentOutline,
  KnowledgeDocumentSection,
  KnowledgeDocumentStatusResponse,
  KnowledgeItem,
  KnowledgeItemCreateInput,
  KnowledgeItemDeleteResponse,
  KnowledgeItemListResponse,
  KnowledgeItemUpdateInput,
  KnowledgeRuntime,
} from "../features/knowledge/knowledge-types"

const KNOWLEDGE_PATH = "/api/knowledge/documents"
const KNOWLEDGE_ITEMS_PATH = "/api/knowledge/items"

export function listKnowledgeDocuments(): Promise<KnowledgeDocumentListResponse> {
  return apiGet(KNOWLEDGE_PATH)
}

export function getKnowledgeDocument(documentId: string): Promise<KnowledgeDocument> {
  return apiGet(`${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}`)
}

export function getKnowledgeDocumentOutline(documentId: string): Promise<KnowledgeDocumentOutline> {
  return apiGet(`${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}/outline`)
}

export function getKnowledgeDocumentSection(
  documentId: string,
  sectionId: string,
): Promise<KnowledgeDocumentSection> {
  return apiGet(
    `${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}/sections/${encodeURIComponent(sectionId)}`,
  )
}

export function getKnowledgeDocumentStatus(
  documentId: string,
): Promise<KnowledgeDocumentStatusResponse> {
  return apiGet(`${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}/status`)
}

export function addKnowledgeDocument(path: string): Promise<KnowledgeDocumentImportResponse> {
  return apiPost(KNOWLEDGE_PATH, { path })
}

export function deleteKnowledgeDocument(documentId: string): Promise<KnowledgeDocumentDeleteResponse> {
  return apiDelete(`${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}`)
}

export function reindexKnowledgeDocument(documentId: string): Promise<KnowledgeDocumentImportResponse> {
  return apiPost(`${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}/reindex`, {})
}

export function getKnowledgeRuntime(): Promise<KnowledgeRuntime> {
  return apiGet("/api/knowledge/runtime")
}

export function listKnowledgeItems(): Promise<KnowledgeItemListResponse> {
  return apiGet(KNOWLEDGE_ITEMS_PATH)
}

export function getKnowledgeItem(itemId: string): Promise<KnowledgeItem> {
  return apiGet(`${KNOWLEDGE_ITEMS_PATH}/${encodeURIComponent(itemId)}`)
}

export function createKnowledgeItem(payload: KnowledgeItemCreateInput): Promise<KnowledgeItem> {
  return apiPost<KnowledgeItem, KnowledgeItemCreateInput>(KNOWLEDGE_ITEMS_PATH, payload)
}

export function updateKnowledgeItem(
  itemId: string,
  payload: KnowledgeItemUpdateInput,
): Promise<KnowledgeItem> {
  return apiPatch<KnowledgeItem, KnowledgeItemUpdateInput>(
    `${KNOWLEDGE_ITEMS_PATH}/${encodeURIComponent(itemId)}`,
    payload,
  )
}

export function deleteKnowledgeItem(itemId: string): Promise<KnowledgeItemDeleteResponse> {
  return apiDelete(`${KNOWLEDGE_ITEMS_PATH}/${encodeURIComponent(itemId)}`)
}
