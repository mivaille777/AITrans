import { ServerOff } from "lucide-react"

import { EmptyState } from "../../shared/ui/EmptyState"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeGraphPanel from "./KnowledgeGraphPanel"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import KnowledgeWorkspace from "./KnowledgeWorkspace"
import type { KnowledgeItem } from "./knowledge-types"
import { useKnowledgeBoard } from "./useKnowledgeBoard"
import { useKnowledgeLibrary } from "./useKnowledgeLibrary"

type BackendState = "checking" | "connected" | "offline"

export default function KnowledgeRoute({ backendState, }: { backendState: BackendState; workspace: TranslationWorkspaceController }) {
  if (backendState !== "connected") {
    return backendState === "checking" ? <section className="ait-surface p-7"><div className="ait-skeleton h-5 w-44 rounded-full" /></section> : <EmptyState icon={<ServerOff size={24} />} title="Knowledge workspace is waiting for the backend" description="Reconnect the backend service to open your knowledge space." />
  }
  return <ConnectedKnowledgeWorkspace />
}

function ConnectedKnowledgeWorkspace() {
  const library = useKnowledgeLibrary()
  const board = useKnowledgeBoard()
  const items = library.itemsQuery.data?.items ?? []
  const focusItemId = items.find((item) => item.item_type === "paper")?.item_id ?? items[0]?.item_id ?? ""
  const openGraph = (itemId: string) => itemId
  const openItem = (item: KnowledgeItem) => item.item_id

  return <KnowledgeWorkspace
    graph={<KnowledgeGraphPanel library={library} board={board} focusItemId={focusItemId} onFocusChange={openGraph} onOpenItem={openItem} />}
    canvas={<KnowledgeBoardPanel library={library} board={board} />}
    library={<KnowledgeLibraryPanel library={library} onOpenPaper={openGraph} onOpenGraph={openGraph} />}
  />
}
