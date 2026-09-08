import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { queryKeys } from "../../shared/query/query-keys"
import {
  createKnowledgeBoard,
  createKnowledgeRelation,
  deleteKnowledgeBoard,
  deleteKnowledgeRelation,
  getKnowledgeBoard,
  listKnowledgeBoards,
  listKnowledgeRelations,
  removeKnowledgeBoardNode,
  updateKnowledgeRelation,
  upsertKnowledgeBoardNode,
} from "./knowledge-api"
import type {
  KnowledgeBoardCreateInput,
  KnowledgeBoardNodeInput,
  KnowledgeRelationCreateInput,
  KnowledgeRelationUpdateInput,
} from "./knowledge-types"

export function useKnowledgeBoard() {
  const queryClient = useQueryClient()
  const [preferredBoardId, setPreferredBoardId] = useState<string | null>(null)

  const boardsQuery = useQuery({
    queryKey: queryKeys.knowledge.boards,
    queryFn: listKnowledgeBoards,
  })
  const relationsQuery = useQuery({
    queryKey: queryKeys.knowledge.relations,
    queryFn: () => listKnowledgeRelations(),
  })

  const boards = boardsQuery.data?.boards ?? []
  const activeBoardId = preferredBoardId && boards.some((board) => board.board_id === preferredBoardId)
    ? preferredBoardId
    : boards[0]?.board_id ?? null
  const setActiveBoardId = setPreferredBoardId

  const boardQuery = useQuery({
    queryKey: queryKeys.knowledge.board(activeBoardId ?? "none"),
    queryFn: () => getKnowledgeBoard(activeBoardId as string),
    enabled: Boolean(activeBoardId),
  })

  const refreshBoard = async (boardId: string | null = activeBoardId) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.boards }),
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.relations }),
      boardId
        ? queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.board(boardId) })
        : Promise.resolve(),
    ])
  }

  const createBoardMutation = useMutation({
    mutationFn: (payload: KnowledgeBoardCreateInput) => createKnowledgeBoard(payload),
    onSuccess: (board) => {
      setPreferredBoardId(board.board_id)
      void refreshBoard(board.board_id)
    },
  })

  const deleteBoardMutation = useMutation({
    mutationFn: deleteKnowledgeBoard,
    onSuccess: (_result, boardId) => {
      if (activeBoardId === boardId) setPreferredBoardId(null)
      void refreshBoard(null)
    },
  })

  const upsertNodeMutation = useMutation({
    mutationFn: ({ itemId, payload }: { itemId: string; payload: KnowledgeBoardNodeInput }) => {
      if (!activeBoardId) throw new Error("No active knowledge board.")
      return upsertKnowledgeBoardNode(activeBoardId, itemId, payload)
    },
    onSuccess: () => void refreshBoard(),
  })

  const removeNodeMutation = useMutation({
    mutationFn: (itemId: string) => {
      if (!activeBoardId) throw new Error("No active knowledge board.")
      return removeKnowledgeBoardNode(activeBoardId, itemId)
    },
    onSuccess: () => void refreshBoard(),
  })

  const createRelationMutation = useMutation({
    mutationFn: (payload: KnowledgeRelationCreateInput) => createKnowledgeRelation(payload),
    onSuccess: () => void refreshBoard(),
  })

  const updateRelationMutation = useMutation({
    mutationFn: ({ relationId, payload }: { relationId: string; payload: KnowledgeRelationUpdateInput }) =>
      updateKnowledgeRelation(relationId, payload),
    onSuccess: () => void refreshBoard(),
  })

  const deleteRelationMutation = useMutation({
    mutationFn: deleteKnowledgeRelation,
    onSuccess: () => void refreshBoard(),
  })

  return {
    activeBoardId,
    setActiveBoardId,
    boardsQuery,
    boardQuery,
    relationsQuery,
    createBoardMutation,
    deleteBoardMutation,
    upsertNodeMutation,
    removeNodeMutation,
    createRelationMutation,
    updateRelationMutation,
    deleteRelationMutation,
  }
}

export type KnowledgeBoardController = ReturnType<typeof useKnowledgeBoard>
