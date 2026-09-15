import { useSearchParams } from "react-router-dom"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeGraphPanel from "./KnowledgeGraphPanel"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import KnowledgePaperReaderPanel from "./KnowledgePaperReaderPanel"
import KnowledgeWorkspaceHeader from "./KnowledgeWorkspaceHeader"
import type { KnowledgeItem } from "./knowledge-types"
import {
  buildCloseReaderParams,
  buildKnowledgeViewParams,
  buildOpenGraphParams,
  buildOpenLibraryItemParams,
  buildOpenPaperParams,
  resolveKnowledgeView,
  type KnowledgePrimaryView,
} from "./knowledge-workspace-navigation"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

export default function KnowledgeWorkspacePanel({
  library,
  board,
  workspace,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
  workspace: TranslationWorkspaceController
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const paperItemId = searchParams.get("paper") ?? ""
  const requestedFocusId = searchParams.get("focus") ?? ""
  const items = library.itemsQuery.data?.items ?? []
  const fallbackFocusId = items.find((item) => item.item_type === "paper")?.item_id ?? items[0]?.item_id ?? ""
  const graphFocusId = requestedFocusId || fallbackFocusId
  const view = resolveKnowledgeView(searchParams)

  function setView(nextView: KnowledgePrimaryView) {
    setSearchParams(buildKnowledgeViewParams(searchParams, nextView), { replace: true })
  }

  function openPaper(itemId: string) {
    setSearchParams(buildOpenPaperParams(searchParams, itemId))
  }

  function openGraph(itemId: string) {
    setSearchParams(buildOpenGraphParams(searchParams, itemId))
  }

  function openGraphItem(item: KnowledgeItem) {
    if (item.item_type === "paper" && item.resource_document_id) {
      openPaper(item.item_id)
      return
    }
    setSearchParams(buildOpenLibraryItemParams(searchParams, item.item_id))
  }

  function closeReader() {
    setSearchParams(buildCloseReaderParams(searchParams), { replace: true })
  }

  function selectPrimaryView(nextView: KnowledgePrimaryView) {
    if (nextView === "graph" && paperItemId) {
      openGraph(paperItemId)
      return
    }
    setView(nextView)
  }

  return (
    <section className="space-y-3" aria-label="Knowledge workspace">
      <KnowledgeWorkspaceHeader view={view} onSelectView={selectPrimaryView} />

      {view === "canvas" ? <KnowledgeBoardPanel library={library} board={board} /> : null}
      {view === "graph" ? <KnowledgeGraphPanel library={library} board={board} focusItemId={graphFocusId} onFocusChange={openGraph} onOpenItem={openGraphItem} /> : null}
      {view === "library" ? <KnowledgeLibraryPanel library={library} onOpenPaper={openPaper} onOpenGraph={openGraph} /> : null}
      {view === "reader" ? <KnowledgePaperReaderPanel paperItemId={paperItemId} library={library} workspace={workspace} onBack={closeReader} /> : null}
    </section>
  )
}
