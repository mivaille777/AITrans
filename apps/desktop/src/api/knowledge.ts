import { API_BASE_URL, apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./client"
import type {
  KnowledgeBoard,
  KnowledgeBoardCreateInput,
  KnowledgeBoardDeleteResponse,
  KnowledgeBoardListResponse,
  KnowledgeBoardNode,
  KnowledgeBoardNodeDeleteResponse,
  KnowledgeBoardNodeInput,
  KnowledgeBoardSnapshot,
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
  KnowledgeRelation,
  KnowledgeRelationCreateInput,
  KnowledgeRelationDeleteResponse,
  KnowledgeRelationListResponse,
  KnowledgeRelationUpdateInput,
  KnowledgeRuntime,
} from "../features/knowledge/knowledge-types"

const KNOWLEDGE_PATH = "/api/knowledge/documents"
const KNOWLEDGE_ITEMS_PATH = "/api/knowledge/items"
const KNOWLEDGE_BOARDS_PATH = "/api/knowledge/boards"
const KNOWLEDGE_RELATIONS_PATH = "/api/knowledge/relations"

export function listKnowledgeDocuments(): Promise<KnowledgeDocumentListResponse> {
  return apiGet(KNOWLEDGE_PATH)
}

export function getKnowledgeDocument(documentId: string): Promise<KnowledgeDocument> {
  return apiGet(`${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}`)
}

export function getKnowledgeDocumentPreviewUrl(documentId: string): string {
  return `${API_BASE_URL}${KNOWLEDGE_PATH}/${encodeURIComponent(documentId)}/preview`
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

export function listKnowledgeBoards(): Promise<KnowledgeBoardListResponse> {
  return apiGet(KNOWLEDGE_BOARDS_PATH)
}

export function createKnowledgeBoard(payload: KnowledgeBoardCreateInput): Promise<KnowledgeBoard> {
  return apiPost<KnowledgeBoard, KnowledgeBoardCreateInput>(KNOWLEDGE_BOARDS_PATH, payload)
}

export function getKnowledgeBoard(boardId: string): Promise<KnowledgeBoardSnapshot> {
  return apiGet(`${KNOWLEDGE_BOARDS_PATH}/${encodeURIComponent(boardId)}`)
}

export function upsertKnowledgeBoardNode(
  boardId: string,
  itemId: string,
  payload: KnowledgeBoardNodeInput,
): Promise<KnowledgeBoardNode> {
  return apiPut<KnowledgeBoardNode, KnowledgeBoardNodeInput>(
    `${KNOWLEDGE_BOARDS_PATH}/${encodeURIComponent(boardId)}/nodes/${encodeURIComponent(itemId)}`,
    payload,
  )
}

export function removeKnowledgeBoardNode(
  boardId: string,
  itemId: string,
): Promise<KnowledgeBoardNodeDeleteResponse> {
  return apiDelete(
    `${KNOWLEDGE_BOARDS_PATH}/${encodeURIComponent(boardId)}/nodes/${encodeURIComponent(itemId)}`,
  )
}

export function deleteKnowledgeBoard(boardId: string): Promise<KnowledgeBoardDeleteResponse> {
  return apiDelete(`${KNOWLEDGE_BOARDS_PATH}/${encodeURIComponent(boardId)}`)
}

export function listKnowledgeRelations(itemId?: string): Promise<KnowledgeRelationListResponse> {
  const query = itemId ? `?item_id=${encodeURIComponent(itemId)}` : ""
  return apiGet(`${KNOWLEDGE_RELATIONS_PATH}${query}`)
}

export function createKnowledgeRelation(
  payload: KnowledgeRelationCreateInput,
): Promise<KnowledgeRelation> {
  return apiPost<KnowledgeRelation, KnowledgeRelationCreateInput>(KNOWLEDGE_RELATIONS_PATH, payload)
}

export function updateKnowledgeRelation(
  relationId: string,
  payload: KnowledgeRelationUpdateInput,
): Promise<KnowledgeRelation> {
  return apiPatch<KnowledgeRelation, KnowledgeRelationUpdateInput>(
    `${KNOWLEDGE_RELATIONS_PATH}/${encodeURIComponent(relationId)}`,
    payload,
  )
}

export function deleteKnowledgeRelation(
  relationId: string,
): Promise<KnowledgeRelationDeleteResponse> {
  return apiDelete(`${KNOWLEDGE_RELATIONS_PATH}/${encodeURIComponent(relationId)}`)
}