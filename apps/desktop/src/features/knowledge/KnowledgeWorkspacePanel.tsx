import { BookOpenText, LayoutDashboard, LibraryBig, Network } from "lucide-react"
import { useSearchParams } from "react-router-dom"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeGraphPanel from "./KnowledgeGraphPanel"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import KnowledgePaperReaderPanel from "./KnowledgePaperReaderPanel"
import type { KnowledgeItem } from "./knowledge-types"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

type KnowledgeView = "canvas" | "graph" | "library" | "reader"

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
  const requestedView = searchParams.get("view")
  const paperItemId = searchParams.get("paper") ?? ""
  const requestedFocusId = searchParams.get("focus") ?? ""
  const items = library.itemsQuery.data?.items ?? []
  const fallbackFocusId = items.find((item) => item.item_type === "paper")?.item_id ?? items[0]?.item_id ?? ""
  const graphFocusId = requestedFocusId || fallbackFocusId
  const view: KnowledgeView = paperItemId && requestedView === "reader"
    ? "reader"
    : requestedView === "graph"
      ? "graph"
      : searchParams.has("document") || searchParams.has("item") || requestedView === "library"
        ? "library"
        : "canvas"

  function setView(nextView: Exclude<KnowledgeView, "reader">) {
    const next = new URLSearchParams(searchParams)
    next.delete("paper")
    next.delete("document")
    next.delete("item")
    if (nextView !== "graph") next.delete("focus")
    if (nextView === "canvas") next.delete("view")
    else next.set("view", nextView)
    setSearchParams(next, { replace: true })
  }

  function openPaper(itemId: string) {
    const next = new URLSearchParams(searchParams)
    next.set("view", "reader")
    next.set("paper", itemId)
    next.delete("document")
    next.delete("item")
    next.delete("focus")
    setSearchParams(next)
  }

  function openGraph(itemId: string) {
    const next = new URLSearchParams(searchParams)
    next.set("view", "graph")
    next.set("focus", itemId)
    next.delete("paper")
    next.delete("document")
    next.delete("item")
    setSearchParams(next)
  }

  function openGraphItem(item: KnowledgeItem) {
    if (item.item_type === "paper" && item.resource_document_id) {
      openPaper(item.item_id)
      return
    }
    const next = new URLSearchParams(searchParams)
    next.set("view", "library")
    next.set("item", item.item_id)
    next.delete("paper")
    next.delete("document")
    next.delete("focus")
    setSearchParams(next)
  }

  function closeReader() {
    const next = new URLSearchParams(searchParams)
    next.set("view", "library")
    next.delete("paper")
    setSearchParams(next, { replace: true })
  }

  return (
    <section className="space-y-3" aria-label="Knowledge workspace">
      <header className="ait-surface flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Knowledge workspace</p>
          <h1 className="mt-1 text-lg font-semibold text-slate-950">AI Knowledge Space</h1>
          <p className="mt-1 text-xs text-slate-500">Organize papers, concepts, notes, relations, and agent-ready context in one place.</p>
        </div>
        <nav className="flex items-center gap-1 rounded-[14px] border border-slate-200 bg-white p-1 shadow-sm" aria-label="Knowledge workspace view">
          <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "canvas" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => setView("canvas")}><LayoutDashboard size={14} />Canvas</button>
          <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "graph" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => paperItemId ? openGraph(paperItemId) : setView("graph")}><Network size={14} />Graph</button>
          <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "library" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => setView("library")}><LibraryBig size={14} />Library</button>
          {view === "reader" ? <button type="button" className="flex items-center gap-2 rounded-[10px] bg-slate-950 px-3 py-2 text-xs font-semibold text-white shadow-sm"><BookOpenText size={14} />Reader</button> : null}
        </nav>
      </header>

      {view === "canvas" ? <KnowledgeBoardPanel library={library} board={board} /> : null}
      {view === "graph" ? <KnowledgeGraphPanel library={library} board={board} focusItemId={graphFocusId} onFocusChange={openGraph} onOpenItem={openGraphItem} /> : null}
      {view === "library" ? <KnowledgeLibraryPanel library={library} onOpenPaper={openPaper} onOpenGraph={openGraph} /> : null}
      {view === "reader" ? <KnowledgePaperReaderPanel paperItemId={paperItemId} library={library} workspace={workspace} onBack={closeReader} /> : null}
    </section>
  )
}
