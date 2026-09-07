import { LayoutDashboard, LibraryBig } from "lucide-react"
import { useSearchParams } from "react-router-dom"

import KnowledgeBoardPanel from "./KnowledgeBoardPanel"
import KnowledgeLibraryPanel from "./KnowledgeLibraryPanel"
import type { KnowledgeBoardController } from "./useKnowledgeBoard"
import type { KnowledgeLibraryController } from "./useKnowledgeLibrary"

export default function KnowledgeWorkspacePanel({
  library,
  board,
}: {
  library: KnowledgeLibraryController
  board: KnowledgeBoardController
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedView = searchParams.get("view")
  const view = searchParams.has("document") || requestedView === "library" ? "library" : "board"

  function setView(nextView: "board" | "library") {
    const next = new URLSearchParams(searchParams)
    if (nextView === "board") {
      next.delete("view")
      next.delete("document")
    } else {
      next.set("view", "library")
    }
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="space-y-3">
      <nav className="flex items-center gap-1 rounded-[14px] border border-slate-200 bg-white p-1 shadow-sm" aria-label="Knowledge workspace view">
        <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "board" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => setView("board")}><LayoutDashboard size={14} />Board</button>
        <button type="button" className={`flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs font-semibold transition ${view === "library" ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`} onClick={() => setView("library")}><LibraryBig size={14} />Library</button>
        <span className="ml-auto hidden pr-2 text-[10px] text-slate-400 sm:inline">{view === "board" ? "Arrange cards and create explicit knowledge relations." : "Manage knowledge cards and local document resources."}</span>
      </nav>
      {view === "board" ? <KnowledgeBoardPanel library={library} board={board} /> : <KnowledgeLibraryPanel library={library} />}
    </div>
  )
}
