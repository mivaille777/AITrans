import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { desktop } from "../../desktop"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import {
  addKnowledgeDocument,
  createKnowledgeItem,
  deleteKnowledgeDocument,
  deleteKnowledgeItem,
  getKnowledgeRuntime,
  listKnowledgeDocuments,
  listKnowledgeItems,
  reindexKnowledgeDocument,
  updateKnowledgeItem,
} from "./knowledge-api"
import { hasActiveKnowledgeDocuments } from "./knowledge-state"
import type { KnowledgeItemCreateInput, KnowledgeItemUpdateInput } from "./knowledge-types"

export function useKnowledgeLibrary() {
  const queryClient = useQueryClient()
  const documentsQuery = useQuery({
    queryKey: queryKeys.knowledge.documents,
    queryFn: listKnowledgeDocuments,
    refetchInterval: (query) =>
      hasActiveKnowledgeDocuments(query.state.data?.documents ?? [])
        ? queryPolling.knowledgeActiveDocuments
        : queryPolling.knowledgeDocuments,
  })
  const itemsQuery = useQuery({
    queryKey: queryKeys.knowledge.items,
    queryFn: listKnowledgeItems,
    refetchInterval: queryPolling.knowledgeDocuments,
  })
  const runtimeQuery = useQuery({
    queryKey: queryKeys.knowledge.runtime,
    queryFn: getKnowledgeRuntime,
    refetchInterval: queryPolling.knowledgeDocuments,
  })

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.documents }),
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.items }),
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.runtime }),
    ])
  }
  const addMutation = useMutation({
    mutationFn: async () => {
      const path = await desktop.files.pickKnowledgeDocument()
      if (!path) return null
      return addKnowledgeDocument(path)
    },
    onSuccess: (result) => {
      if (result) void refresh()
    },
  })
  const createItemMutation = useMutation({
    mutationFn: (payload: KnowledgeItemCreateInput) => createKnowledgeItem(payload),
    onSuccess: () => void refresh(),
  })
  const updateItemMutation = useMutation({
    mutationFn: ({ itemId, payload }: { itemId: string; payload: KnowledgeItemUpdateInput }) =>
      updateKnowledgeItem(itemId, payload),
    onSuccess: () => void refresh(),
  })
  const deleteItemMutation = useMutation({
    mutationFn: deleteKnowledgeItem,
    onSuccess: () => void refresh(),
  })
  const deleteMutation = useMutation({
    mutationFn: deleteKnowledgeDocument,
    onSuccess: () => void refresh(),
  })
  const reindexMutation = useMutation({
    mutationFn: reindexKnowledgeDocument,
    onSuccess: () => void refresh(),
  })

  return {
    documentsQuery,
    itemsQuery,
    runtimeQuery,
    addMutation,
    createItemMutation,
    updateItemMutation,
    deleteItemMutation,
    deleteMutation,
    reindexMutation,
  }
}

export type KnowledgeLibraryController = ReturnType<typeof useKnowledgeLibrary>
