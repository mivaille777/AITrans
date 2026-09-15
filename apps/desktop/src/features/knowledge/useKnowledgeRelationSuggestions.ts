import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { queryKeys } from "../../shared/query/query-keys"
import {
  acceptKnowledgeRelationSuggestion,
  generateKnowledgeRelationSuggestions,
  listKnowledgeRelationSuggestions,
  rejectKnowledgeRelationSuggestion,
} from "./knowledge-api"
import type { KnowledgeRelationSuggestionGenerateInput } from "./knowledge-types"

export function useKnowledgeRelationSuggestions(focusItemId: string) {
  const queryClient = useQueryClient()
  const suggestionsQuery = useQuery({
    queryKey: queryKeys.knowledge.relationSuggestions(focusItemId || "none"),
    queryFn: () => listKnowledgeRelationSuggestions(focusItemId, "pending"),
    enabled: Boolean(focusItemId),
  })

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.knowledge.relationSuggestions(focusItemId || "none"),
      }),
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.relations }),
    ])
  }

  const generateMutation = useMutation({
    mutationFn: (payload: KnowledgeRelationSuggestionGenerateInput) =>
      generateKnowledgeRelationSuggestions(payload),
    onSuccess: () => void refresh(),
  })

  const acceptMutation = useMutation({
    mutationFn: acceptKnowledgeRelationSuggestion,
    onSuccess: () => void refresh(),
  })

  const rejectMutation = useMutation({
    mutationFn: rejectKnowledgeRelationSuggestion,
    onSuccess: () => void refresh(),
  })

  return {
    suggestionsQuery,
    generateMutation,
    acceptMutation,
    rejectMutation,
  }
}

export type KnowledgeRelationSuggestionController = ReturnType<
  typeof useKnowledgeRelationSuggestions
>
