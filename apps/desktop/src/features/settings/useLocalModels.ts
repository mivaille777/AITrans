import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { downloadRagModel, listRagModels, removeRagModel, verifyRagModel, type RagModelId } from "../../api/rag-models"
import { queryKeys } from "../../shared/query/query-keys"

export function useLocalModels() {
  const queryClient = useQueryClient()
  const modelsQuery = useQuery({
    queryKey: queryKeys.ragModels.list,
    queryFn: listRagModels,
    refetchInterval: (query) => query.state.data?.models.some((model) => model.state === "downloading") ? 1_000 : 10_000,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.ragModels.list })
  const downloadMutation = useMutation({ mutationFn: (modelId: RagModelId) => downloadRagModel(modelId), onSettled: () => void refresh() })
  const verifyMutation = useMutation({ mutationFn: (modelId: RagModelId) => verifyRagModel(modelId), onSettled: () => void refresh() })
  const removeMutation = useMutation({ mutationFn: (modelId: RagModelId) => removeRagModel(modelId), onSettled: () => void refresh() })
  return { modelsQuery, downloadMutation, verifyMutation, removeMutation }
}

export type LocalModelsController = ReturnType<typeof useLocalModels>
