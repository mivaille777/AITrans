import { ServerOff } from "lucide-react"

import { EmptyState } from "../../shared/ui/EmptyState"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeGraphPanel from "./KnowledgeGraphPanel"
import KnowledgeHome from "./KnowledgeHome"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import KnowledgeWorkspace from "./KnowledgeWorkspace"
import { useKnowledgeBoard } from "./useKnowledgeBoard"
import { useKnowledgeLibrary } from "./useKnowledgeLibrary"

type BackendState = "checking" | "connected" | "offline"

export default function KnowledgeRoute({ backendState, workspace: _workspace }: { backendState: BackendState; workspace: TranslationWorkspaceController }) {
  if (backendState !== "connected") {
    return backendState === "checking" ? (
      <section className="ait-surface p-7"><div className="ait-skeleton h-5 w-44 rounded-full" /></section>
    ) : (
      <EmptyState icon={<ServerOff size={24} />} title="Knowledge workspace is waiting for the backend" description="Reconnect the backend service to open your knowledge space." />
    )
  }

  return <ConnectedKnowledgeWorkspace />
}

function ConnectedKnowledgeWorkspace() {
  const library = useKnowledgeLibrary()
  const board = useKnowledgeBoard()
  const items = library.itemsQuery.data?.items ?? []
  const paperCount = items.filter((item) => item.item_type === "paper").length
  const conceptCount = items.filter((item) => item.item_type !== "paper").length

  return (
    <div className="space-y-4">
      <KnowledgeHome
        paperCount={paperCount}
        conceptCount={conceptCount}
        relationCount={Math.max(items.length - 1, 0)}
        onOpenCanvas={() => undefined}
        onOpenGraph={() => undefined}
      />
      <KnowledgeWorkspace
        graph={<KnowledgeGraphPanel library={library} board={board} focusItemId={items[0]?.item_id ?? ""} onFocusChange={() => undefined} onOpenItem={() => undefined} />}
        canvas={<KnowledgeBoardPanel library={library} board={board} />}
        library={<KnowledgeLibraryPanel library={library} onOpenPaper={() => undefined} onOpenGraph={() => undefined} />}
      />
    </div>
  )
}
