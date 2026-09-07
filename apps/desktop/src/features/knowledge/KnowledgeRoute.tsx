import { ServerOff } from "lucide-react"

import { EmptyState } from "../../shared/ui/EmptyState"
import KnowledgeWorkspacePanel from "./KnowledgeWorkspacePanel"
import { useKnowledgeBoard } from "./useKnowledgeBoard"
import { useKnowledgeLibrary } from "./useKnowledgeLibrary"

type BackendState = "checking" | "connected" | "offline"

export default function KnowledgeRoute({ backendState }: { backendState: BackendState }) {
  if (backendState !== "connected") {
    return backendState === "checking" ? (
      <section className="ait-surface overflow-hidden p-7" aria-busy="true">
        <div className="ait-skeleton h-5 w-44 rounded-full" />
        <div className="ait-skeleton mt-5 h-32 rounded-[18px]" />
      </section>
    ) : (
      <EmptyState
        className="ait-surface border-solid bg-white/90 py-16"
        icon={<ServerOff size={24} strokeWidth={1.6} />}
        title="Knowledge workspace is waiting for the backend"
        description="Reconnect the local AITranslator service to open your board, cards, and document index."
      />
    )
  }

  return <ConnectedKnowledgeWorkspace />
}

function ConnectedKnowledgeWorkspace() {
  const library = useKnowledgeLibrary()
  const board = useKnowledgeBoard()
  return <KnowledgeWorkspacePanel library={library} board={board} />
}
