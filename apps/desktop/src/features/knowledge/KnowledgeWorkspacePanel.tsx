import { Navigate, useNavigate, useSearchParams } from "react-router-dom"
import { useEffect, useState } from "react"

import { buildReadingPaperPath } from "../reading/reading-navigation"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeGraphPanel from "./KnowledgeGraphPanel"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import KnowledgeWorkspaceHeader from "./KnowledgeWorkspaceHeader"
import "./KnowledgeWorkspace.css"
import type { KnowledgeItem } from "./knowledge-types"
import {
  buildKnowledgeViewParams,
  buildOpenGraphParams,
  buildOpenLibraryItemParams,
  resolveKnowledgeView,
  resolveLegacyKnowledgeReaderPaperId,
  type KnowledgePrimaryView,
} from "./knowledge-workspace-navigation"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

export default function KnowledgeWorkspacePanel({
  library,
  board,
  workspace: _workspace,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
  workspace: TranslationWorkspaceController
}) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedFocusId = searchParams.get("focus") ?? ""
  const items = library.itemsQuery.data?.items ?? []
  const fallbackFocusId = items.find((item) => item.item_type === "paper")?.item_id ?? items[0]?.item_id ?? ""
  const graphFocusId = requestedFocusId || fallbackFocusId
  const view = resolveKnowledgeView(searchParams)
  const legacyReaderPaperId = resolveLegacyKnowledgeReaderPaperId(searchParams)
  const [visitedViews, setVisitedViews] = useState<Set<KnowledgePrimaryView>>(() => new Set([view]))
  const [searchRequest, setSearchRequest] = useState(0)
  const [newRequest, setNewRequest] = useState(0)

  /* oxlint-disable react/set-state-in-effect -- retain each knowledge view after its first visit */
  useEffect(() => {
    setVisitedViews((current) => {
      if (current.has(view)) return current
      return new Set(current).add(view)
    })
  }, [view])
  /* oxlint-enable react/set-state-in-effect */

  if (legacyReaderPaperId) {
    return <Navigate to={buildReadingPaperPath(legacyReaderPaperId)} replace />
  }

  function setView(nextView: KnowledgePrimaryView) {
    setSearchParams(buildKnowledgeViewParams(searchParams, nextView), { replace: true })
  }

  function openPaper(itemId: string) {
    navigate(buildReadingPaperPath(itemId))
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

  function requestSearch() {
    if (view === "graph") setView("canvas")
    setSearchRequest((request) => request + 1)
  }

  function requestNew() {
    if (view !== "canvas") setView("canvas")
    setNewRequest((request) => request + 1)
  }

  return (
    <section className="knowledge-workspace" aria-label="Knowledge workspace">
      <KnowledgeWorkspaceHeader view={view} onSelectView={setView} onSearch={requestSearch} onNew={requestNew} />

      <div className="knowledge-workspace-body">
        {(["canvas", "graph", "library"] as const).map((panelView) => {
          const visible = view === panelView
          if (!visible && !visitedViews.has(panelView)) return null
          return (
            <div
              key={panelView}
              className={visible ? "min-h-0 flex-1" : "hidden"}
              aria-hidden={!visible}
            >
              {panelView === "canvas" ? <KnowledgeBoardPanel library={library} board={board} focusSearchRequest={searchRequest} createCardRequest={newRequest} /> : null}
              {panelView === "graph" ? <KnowledgeGraphPanel library={library} board={board} focusItemId={graphFocusId} onFocusChange={openGraph} onOpenItem={openGraphItem} /> : null}
              {panelView === "library" ? <KnowledgeLibraryPanel library={library} onOpenPaper={openPaper} onOpenGraph={openGraph} focusSearchRequest={searchRequest} createCardRequest={newRequest} /> : null}
            </div>
          )
        })}
      </div>
    </section>
  )
}
