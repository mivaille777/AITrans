import { useContext } from "react"

import { KnowledgeWorkspaceContext } from "./knowledge-workspace-context"

export function useOptionalKnowledgeWorkspaceContext() {
  return useContext(KnowledgeWorkspaceContext)
}

export function useKnowledgeWorkspaceContext() {
  const context = useOptionalKnowledgeWorkspaceContext()
  if (!context) {
    throw new Error("useKnowledgeWorkspaceContext must be used inside KnowledgeWorkspaceProvider")
  }
  return context
}
